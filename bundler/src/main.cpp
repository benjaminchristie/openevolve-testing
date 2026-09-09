#include <bundler/bundler.hpp>
#include <cstring>
#include <iomanip>
#include <random>

namespace fs = std::filesystem;
using json = nlohmann::json;

namespace {
bool contains(const std::vector<std::string>& v, const std::string& s) {
    return std::find(v.begin(), v.end(), s) != v.end();
}
}  // namespace

// add a language: one grammar in CMakeLists.txt (add_tree_sitter_grammar) + one entry here
const std::vector<LanguageSpec>& language_registry() {
    static const std::vector<LanguageSpec> registry = {
        {
            "cpp",
            {".cpp", ".hpp", ".cc", ".h", ".cxx"},
            tree_sitter_cpp,
            "//",
            {"function_definition"},
            {"template_declaration"},
            {"parameter_list", "compound_statement"},
        },
        {
            "c",
            {".c"},
            tree_sitter_c,
            "//",
            {"function_definition"},
            {},
            {"parameter_list", "compound_statement"},
        },
        {
            "python",
            {".py"},
            tree_sitter_python,
            "#",
            {"function_definition"},
            {"decorated_definition"},
            {"parameters", "block"},
        },
    };
    return registry;
}

const LanguageSpec* language_for_extension(const std::string& extension) {
    for (const auto& lang : language_registry()) {
        if (contains(lang.extensions, extension)) return &lang;
    }
    return nullptr;
}

// per-run random token so block delimiters can't collide with text inside evolved code
std::string generate_run_token() {
    std::random_device rd;
    std::mt19937_64 gen(rd());
    std::uniform_int_distribution<uint64_t> dist;
    std::stringstream ss;
    ss << std::hex << std::setw(16) << std::setfill('0') << dist(gen);
    return ss.str();
}


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

std::string trim(const std::string& s) {
    size_t start = s.find_first_not_of(" \t\r\n");
    if (start == std::string::npos) return "";
    size_t end = s.find_last_not_of(" \t\r\n");
    return s.substr(start, end - start + 1);
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

TSNode get_associated_function_node(TSNode comment_node, const LanguageSpec& lang) {
    TSNode curr = comment_node;
    TSNode func_node = {};

    while (!ts_node_is_null(curr)) {
        std::string type = ts_node_type(curr);
        if (contains(lang.block_node_types, type)) {
            func_node = curr;
            break;
        }
        curr = ts_node_parent(curr);
    }

    if (ts_node_is_null(func_node)) {
        curr = ts_node_next_sibling(comment_node);
        while (!ts_node_is_null(curr)) {
            std::string type = ts_node_type(curr);
            if (contains(lang.block_node_types, type) || contains(lang.wrapper_node_types, type)) {
                func_node = curr;
                break;
            }
            if (type != "comment") break;
            curr = ts_node_next_sibling(curr);
        }
    }

    if (!ts_node_is_null(func_node)) {
        TSNode parent = ts_node_parent(func_node);
        if (!ts_node_is_null(parent) && contains(lang.wrapper_node_types, std::string(ts_node_type(parent)))) {
            func_node = parent;
        }
    }

    return func_node;
}

TSNode get_function_name_node(TSNode node, const LanguageSpec& lang) {
    // for a wrapper (Python's decorated_definition, C++'s template_declaration), look up
    // the name on the block node inside it -- else a decorator's own identifier
    // (e.g. "staticmethod" in @staticmethod) gets mistaken for the function's name
    std::string node_type = ts_node_type(node);
    if (contains(lang.wrapper_node_types, node_type)) {
        uint32_t wrapper_child_count = ts_node_child_count(node);
        for (uint32_t i = 0; i < wrapper_child_count; ++i) {
            TSNode child = ts_node_child(node, i);
            std::string child_type = ts_node_type(child);
            if (contains(lang.block_node_types, child_type) || contains(lang.wrapper_node_types, child_type)) {
                return get_function_name_node(child, lang);
            }
        }
        return {};
    }

    // fast path: most grammars expose the name directly via a "name" field
    TSNode name_field = ts_node_child_by_field_name(node, "name", static_cast<uint32_t>(strlen("name")));
    if (!ts_node_is_null(name_field)) return name_field;

    // fallback: name is nested in a declarator chain (C/C++ pointer/template return types, ...)
    std::string type = ts_node_type(node);
    if (type == "identifier" || type == "field_identifier" || type == "destructor_name") {
        return node;
    }
    uint32_t count = ts_node_child_count(node);
    for (uint32_t i = 0; i < count; ++i) {
        TSNode child = ts_node_child(node, i);
        std::string child_type = ts_node_type(child);
        if (contains(lang.name_search_skip_types, child_type)) continue;
        TSNode res = get_function_name_node(child, lang);
        if (!ts_node_is_null(res)) return res;
    }
    return {};
}
/** 
@evolve(one)
*/
void extract_blocks(const std::string& src_dir, const std::string& bundle_out, const std::string& map_out, const std::string& target_group) {
    TSParser* parser = ts_parser_new();

    std::vector<BlockMetadata> metadata_list;
    std::vector<std::string> mangled_snippets;
    std::set<std::tuple<std::string, size_t, size_t>> seen_function_ranges;
    std::set<std::string> languages_seen;
    // comment style for the bundle's own markers, taken from the first block's language
    // (keeps a Python bundle valid Python, not C-style "//")
    std::string bundle_comment_prefix = "//";
    bool bundle_comment_prefix_set = false;

    std::regex evolve_regex(R"(@evolve(?:\(\s*([a-zA-Z0-9_]*)\s*\))?)");

    int block_counter = 0;

    for (const auto& entry : fs::recursive_directory_iterator(src_dir)) {
        if (!entry.is_regular_file()) continue;
        auto ext = entry.path().extension().string();
        const LanguageSpec* lang_ptr = language_for_extension(ext);
        if (lang_ptr == nullptr) continue;
        const LanguageSpec& lang = *lang_ptr;
        languages_seen.insert(lang.name);

        std::string path = entry.path().string();
        std::string source = read_file(path);

        ts_parser_set_language(parser, lang.get_language());
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

                TSNode func_node = get_associated_function_node(comment.node, lang);
                if (ts_node_is_null(func_node)) continue;

                size_t final_start = ts_node_start_byte(func_node);
                size_t final_end = ts_node_end_byte(func_node);

                if (seen_function_ranges.count({path, final_start, final_end}) > 0) continue;
                seen_function_ranges.insert({path, final_start, final_end});

                std::string snippet = source.substr(final_start, final_end - final_start);
                std::string orig_name = "";
                std::string mangled_name = "";

                TSNode name_node = get_function_name_node(func_node, lang);
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
                mangled_snippets.push_back(snippet);
                if (!bundle_comment_prefix_set) {
                    bundle_comment_prefix = lang.line_comment_prefix;
                    bundle_comment_prefix_set = true;
                }
                block_counter++;
            }
        }
        ts_tree_delete(tree);
    }
    ts_parser_delete(parser);

    std::string run_token = generate_run_token();

    const std::string& cp = bundle_comment_prefix;  // shorthand
    std::stringstream bundle_stream;
    bundle_stream << cp << " ==========================================\n";
    bundle_stream << cp << " AUTO-GENERATED BUNDLE FOR OPENEVOLVE\n";
    if (!target_group.empty()) {
        bundle_stream << cp << " TARGET GROUP: " << target_group << "\n";
    }
    bundle_stream << cp << " ==========================================\n\n";
    bundle_stream << cp << " EVOLVE-BLOCK-START\n\n";

    for (size_t i = 0; i < metadata_list.size(); ++i) {
        const auto& meta = metadata_list[i];
        bundle_stream << cp << " >>> OPENEVOLVE_BLOCK token=" << run_token << " id=" << meta.id
                      << " group=" << meta.group_id << " file=" << meta.file_path << " <<<\n";
        bundle_stream << mangled_snippets[i] << "\n\n";
    }

    bundle_stream << cp << " EVOLVE-BLOCK-END\n";

    json blocks_json = json::array();
    for (const auto& meta : metadata_list) {
        blocks_json.push_back({
            {"id", meta.id},
            {"group_id", meta.group_id},
            {"file_path", meta.file_path},
            {"start_byte", meta.start_byte},
            {"end_byte", meta.end_byte},
            {"orig_name", meta.orig_name},
            {"mangled_name", meta.mangled_name}
        });
    }
    json json_map = {
        {"token", run_token},
        {"comment_prefix", bundle_comment_prefix},
        {"blocks", blocks_json}
    };

    write_file(bundle_out, bundle_stream.str());
    write_file(map_out, json_map.dump(4));

    if (languages_seen.size() > 1) {
        std::cerr << "[Bundler] WARNING: extracted blocks span multiple languages (";
        bool first = true;
        for (const auto& l : languages_seen) {
            if (!first) std::cerr << ", ";
            std::cerr << l;
            first = false;
        }
        std::cerr << ") into a single bundle. OpenEvolve evolves one program in one "
                  << "language, so this bundle will most likely not build -- scope "
                  << "--group (or --src) so each bundle covers a single language.\n";
    }

    std::cout << "[Bundler] Extracted " << metadata_list.size() << " functions into " << bundle_out
              << " (Filter: " << (target_group.empty() ? "ALL" : target_group) << ")\n";
}

void inject_blocks(const std::string& bundle_in, const std::string& map_in) {
    std::string bundle_text = read_file(bundle_in);
    std::string map_text = read_file(map_in);
    json json_map = json::parse(map_text);

    if (!json_map.contains("token") || !json_map.contains("blocks")) {
        throw std::runtime_error("Map file is missing required 'token'/'blocks' fields (stale format?).");
    }
    std::string run_token = json_map["token"];
    std::string comment_prefix = json_map.value("comment_prefix", "//");  // older maps predate this field, always "//"
    const json& blocks_json = json_map["blocks"];

    std::string delimiter_prefix = comment_prefix + " >>> OPENEVOLVE_BLOCK token=" + run_token + " id=";
    std::regex id_regex("^" + comment_prefix + R"( >>> OPENEVOLVE_BLOCK token=[0-9a-f]+ id=(\d+))");
    std::string end_marker = comment_prefix + " EVOLVE-BLOCK-END";

    std::map<int, std::string> mutated_blocks;
    std::istringstream stream(bundle_text);
    std::string line;

    int current_id = -1;
    std::stringstream current_snippet;

    while (std::getline(stream, line)) {
        std::string trimmed = trim(line);
        std::smatch match;
        // anchored to line start, not matched anywhere in the line -- otherwise a
        // block whose own source contains this text (e.g. bundler evolving itself)
        // gets misparsed as a boundary
        if (trimmed.rfind(delimiter_prefix, 0) == 0 && std::regex_search(trimmed, match, id_regex)) {
            if (current_id != -1) {
                mutated_blocks[current_id] = trim(current_snippet.str());  // trim: drop the blank-line separator
                current_snippet.str("");
                current_snippet.clear();
            }
            current_id = std::stoi(match[1].str());
        } else if (trimmed == end_marker) {
            if (current_id != -1) {
                mutated_blocks[current_id] = trim(current_snippet.str());
            }
            break;
        } else if (current_id != -1) {
            current_snippet << line << "\n";
        }
    }

    std::map<std::string, std::vector<BlockMetadata>> file_group;
    for (const auto& item : blocks_json) {
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