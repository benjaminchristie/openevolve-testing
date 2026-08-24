#include <bundler/bundler.hpp>

namespace fs = std::filesystem;
using json = nlohmann::json;


struct CLIArgs {
    std::string mode = "";
    std::string src_dir = "";
    std::string bundle_path = "";
    std::string map_path = "";
    std::string group_id = ""; // Empty string means match all / universal only
};

std::string read_file(const std::string& path) {
    std::ifstream in(path, std::ios::in | std::ios::binary);
    if (!in) throw std::runtime_error("Failed to open file: " + path);
    std::ostringstream contents;
    contents << in.rdbuf();
    return contents.str();
}

void write_file(const std::string& path, const std::string& content) {
    std::ofstream out(path, std::ios::out | std::ios::binary);
    if (!out) throw std::runtime_error("Failed to write file: " + path);
    out << content;
}

void collect_comments(TSNode node, const std::string& source, std::vector<CommentNodeInfo>& comments) {
    if (std::string(ts_node_type(node)) == "comment") {
        comments.push_back({node, ts_node_start_byte(node), ts_node_end_byte(node)});
    }
    uint32_t child_count = ts_node_child_count(node);
    for (uint32_t i = 0; i < child_count; ++i) {
        collect_comments(ts_node_child(node, i), source, comments);
    }
}

TSNode get_associated_function_node(TSNode comment_node) {
    TSNode curr = comment_node;
    TSNode func_node = {};

    while (!ts_node_is_null(curr)) {
        std::string type = ts_node_type(curr);
        if (type == "function_definition") {
            func_node = curr;
            break;
        }
        curr = ts_node_parent(curr);
    }

    if (ts_node_is_null(func_node)) {
        curr = ts_node_next_sibling(comment_node);
        while (!ts_node_is_null(curr)) {
            std::string type = ts_node_type(curr);
            if (type == "function_definition" || type == "template_declaration") {
                func_node = curr;
                break;
            }
            if (type != "comment") break;
            curr = ts_node_next_sibling(curr);
        }
    }

    if (!ts_node_is_null(func_node)) {
        TSNode parent = ts_node_parent(func_node);
        if (!ts_node_is_null(parent) && std::string(ts_node_type(parent)) == "template_declaration") {
            func_node = parent;
        }
    }

    return func_node;
}

TSNode get_function_name_node(TSNode node) {
    std::string type = ts_node_type(node);
    if (type == "identifier" || type == "field_identifier" || type == "destructor_name") {
        return node;
    }
    uint32_t count = ts_node_child_count(node);
    for (uint32_t i = 0; i < count; ++i) {
        TSNode child = ts_node_child(node, i);
        std::string child_type = ts_node_type(child);
        if (child_type == "parameter_list" || child_type == "compound_statement") continue;
        TSNode res = get_function_name_node(child);
        if (!ts_node_is_null(res)) return res;
    }
    return {};
}
/** 
@evolve(one)
*/
void extract_blocks(const std::string& src_dir, const std::string& bundle_out, const std::string& map_out, const std::string& target_group) {
    TSParser* parser = ts_parser_new();
    ts_parser_set_language(parser, tree_sitter_cpp());

    std::vector<BlockMetadata> metadata_list;
    std::set<std::tuple<std::string, size_t, size_t>> seen_function_ranges;
    
    std::regex evolve_regex(R"(@evolve(?:\(\s*([a-zA-Z0-9_]*)\s*\))?)");

    int block_counter = 0;

    for (const auto& entry : fs::recursive_directory_iterator(src_dir)) {
        if (!entry.is_regular_file()) continue;
        auto ext = entry.path().extension().string();
        if (ext != ".cpp" && ext != ".hpp" && ext != ".cc" && ext != ".h" && ext != ".cxx") continue;

        std::string path = entry.path().string();
        std::string source = read_file(path);

        TSTree* tree = ts_parser_parse_string(parser, nullptr, source.c_str(), source.length());
        TSNode root = ts_tree_root_node(tree);

        std::vector<CommentNodeInfo> comments;
        collect_comments(root, source, comments);

        for (const auto& comment : comments) {
            std::string comment_text = source.substr(comment.start_byte, comment.end_byte - comment.start_byte);
            std::smatch match;

            if (std::regex_search(comment_text, match, evolve_regex)) {
                std::string func_group = match[1].matched ? match[1].str() : "";

                // Universal check: if func_group is empty, it belongs to ALL runs.
                // Otherwise, verify group match.
                bool is_universal = func_group.empty();
                bool matches_group = target_group.empty() || target_group == "all" || func_group == target_group;

                if (!is_universal && !matches_group) {
                    continue;
                }

                TSNode func_node = get_associated_function_node(comment.node);
                if (ts_node_is_null(func_node)) continue;

                size_t final_start = ts_node_start_byte(func_node);
                size_t final_end = ts_node_end_byte(func_node);

                if (seen_function_ranges.count({path, final_start, final_end}) > 0) continue;
                seen_function_ranges.insert({path, final_start, final_end});

                std::string snippet = source.substr(final_start, final_end - final_start);
                std::string orig_name = "";
                std::string mangled_name = "";

                TSNode name_node = get_function_name_node(func_node);
                if (!ts_node_is_null(name_node)) {
                    size_t name_start = ts_node_start_byte(name_node);
                    size_t name_end = ts_node_end_byte(name_node);

                    orig_name = source.substr(name_start, name_end - name_start);
                    mangled_name = orig_name + "_block_" + std::to_string(block_counter);

                    size_t rel_start = name_start - final_start;
                    size_t rel_len = name_end - name_start;
                    snippet.replace(rel_start, rel_len, mangled_name);
                }

                metadata_list.push_back({
                    block_counter, 
                    is_universal ? "universal" : func_group, 
                    path, 
                    final_start, 
                    final_end, 
                    orig_name, 
                    mangled_name
                });
                block_counter++;
            }
        }
        ts_tree_delete(tree);
    }
    ts_parser_delete(parser);

    std::stringstream bundle_stream;
    bundle_stream << "// ==========================================\n";
    bundle_stream << "// AUTO-GENERATED BUNDLE FOR OPENEVOLVE\n";
    if (!target_group.empty()) {
        bundle_stream << "// TARGET GROUP: " << target_group << "\n";
    }
    bundle_stream << "// ==========================================\n\n";
    bundle_stream << "// EVOLVE-BLOCK-START\n\n";

    for (const auto& meta : metadata_list) {
        std::string source = read_file(meta.file_path);
        std::string snippet = source.substr(meta.start_byte, meta.end_byte - meta.start_byte);
        if (!meta.mangled_name.empty() && !meta.orig_name.empty()) {
            snippet.replace(snippet.find(meta.orig_name), meta.orig_name.length(), meta.mangled_name);
        }

        bundle_stream << "// --- GROUP: " << meta.group_id << " | BLOCK_ID: " << meta.id << " (" << meta.file_path << ") ---\n";
        bundle_stream << snippet << "\n\n";
    }

    bundle_stream << "// EVOLVE-BLOCK-END\n";

    json json_map = json::array();
    for (const auto& meta : metadata_list) {
        json_map.push_back({
            {"id", meta.id},
            {"group_id", meta.group_id},
            {"file_path", meta.file_path},
            {"start_byte", meta.start_byte},
            {"end_byte", meta.end_byte},
            {"orig_name", meta.orig_name},
            {"mangled_name", meta.mangled_name}
        });
    }

    write_file(bundle_out, bundle_stream.str());
    write_file(map_out, json_map.dump(4));

    std::cout << "[Bundler] Extracted " << metadata_list.size() << " functions into " << bundle_out 
              << " (Filter: " << (target_group.empty() ? "ALL" : target_group) << ")\n";
}

void inject_blocks(const std::string& bundle_in, const std::string& map_in) {
    std::string bundle_text = read_file(bundle_in);
    std::string map_text = read_file(map_in);
    json json_map = json::parse(map_text);

    std::map<int, std::string> mutated_blocks;
    std::istringstream stream(bundle_text);
    std::string line;
    
    int current_id = -1;
    std::stringstream current_snippet;

    while (std::getline(stream, line)) {
        if (line.find("BLOCK_ID:") != std::string::npos) {
            if (current_id != -1) {
                mutated_blocks[current_id] = current_snippet.str();
                current_snippet.str("");
                current_snippet.clear();
            }
            size_t id_pos = line.find("BLOCK_ID:") + 10;
            current_id = std::stoi(line.substr(id_pos));
        } else if (line.find("// EVOLVE-BLOCK-END") != std::string::npos) {
            if (current_id != -1) {
                mutated_blocks[current_id] = current_snippet.str();
            }
            break;
        } else if (current_id != -1) {
            current_snippet << line << "\n";
        }
    }

    std::map<std::string, std::vector<BlockMetadata>> file_group;
    for (const auto& item : json_map) {
        file_group[item["file_path"]].push_back({
            item["id"],
            item["group_id"],
            item["file_path"],
            item["start_byte"],
            item["end_byte"],
            item.value("orig_name", ""),
            item.value("mangled_name", "")
        });
    }

    for (auto& [file_path, blocks] : file_group) {
        std::sort(blocks.begin(), blocks.end(), [](const BlockMetadata& a, const BlockMetadata& b) {
            return a.start_byte > b.start_byte;
        });

        std::string file_content = read_file(file_path);

        for (const auto& block : blocks) {
            if (mutated_blocks.find(block.id) != mutated_blocks.end()) {
                std::string new_code = mutated_blocks[block.id];

                if (!block.mangled_name.empty() && !block.orig_name.empty()) {
                    size_t pos = 0;
                    while ((pos = new_code.find(block.mangled_name, pos)) != std::string::npos) {
                        new_code.replace(pos, block.mangled_name.length(), block.orig_name);
                        pos += block.orig_name.length();
                    }
                }

                file_content.replace(block.start_byte, block.end_byte - block.start_byte, new_code);
            }
        }
        write_file(file_path, file_content);
    }

    std::cout << "[Bundler] Successfully reinjected annotated blocks across " << file_group.size() << " files.\n";
}

CLIArgs parse_cli_args(int argc, char* argv[]) {
    CLIArgs args;
    for (int i = 1; i < argc; ++i) {
        std::string arg = argv[i];
        if ((arg == "--mode" || arg == "-m") && i + 1 < argc) {
            args.mode = argv[++i];
        } else if ((arg == "--src" || arg == "-s") && i + 1 < argc) {
            args.src_dir = argv[++i];
        } else if ((arg == "--bundle" || arg == "-b") && i + 1 < argc) {
            args.bundle_path = argv[++i];
        } else if ((arg == "--map" || arg == "-p") && i + 1 < argc) {
            args.map_path = argv[++i];
        } else if ((arg == "--group" || arg == "-g") && i + 1 < argc) {
            args.group_id = argv[++i];
        }
    }
    return args;
}

void print_usage(const char* prog_name) {
    std::cerr << "Usage:\n"
              << "  Extraction Mode:\n"
              << "    " << prog_name << " --mode extract --src <dir> --bundle <out.cpp> --map <out.json> [--group <id>]\n\n"
              << "  Injection Mode:\n"
              << "    " << prog_name << " --mode inject --bundle <in.cpp> --map <in.json>\n";
}

int main(int argc, char* argv[]) {
    CLIArgs args = parse_cli_args(argc, argv);

    if (args.mode.empty() || args.bundle_path.empty() || args.map_path.empty()) {
        print_usage(argv[0]);
        return 1;
    }

    try {
        if (args.mode == "extract") {
            if (args.src_dir.empty()) {
                std::cerr << "[Error] --src directory required for extraction mode.\n";
                return 1;
            }
            extract_blocks(args.src_dir, args.bundle_path, args.map_path, args.group_id);
        } else if (args.mode == "inject") {
            inject_blocks(args.bundle_path, args.map_path);
        } else {
            std::cerr << "[Error] Unknown mode: " << args.mode << "\n";
            return 1;
        }
    } catch (const std::exception& e) {
        std::cerr << "[Error] " << e.what() << "\n";
        return 1;
    }

    return 0;
}