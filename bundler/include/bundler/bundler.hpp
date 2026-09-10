#pragma once

#include <algorithm>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <map>
#include <nlohmann/json.hpp>
#include <regex>
#include <set>
#include <sstream>
#include <string>
#include <tree_sitter/api.h>
#include <tuple>
#include <vector>

extern "C" const TSLanguage *tree_sitter_cpp();
extern "C" const TSLanguage *tree_sitter_c();
extern "C" const TSLanguage *tree_sitter_python();

// To add a language: one entry in language_registry() (main.cpp) plus its grammar in CMakeLists.txt
struct LanguageSpec {
	std::string name;
	std::vector<std::string> extensions;
	const TSLanguage *(*get_language)();
	std::string line_comment_prefix;
	std::vector<std::string> block_node_types;  // e.g. {"function_definition"}
	std::vector<std::string> wrapper_node_types;  // e.g. C++ templates, Python decorators
	std::vector<std::string> name_search_skip_types;  // used by get_function_name_node's fallback
};

struct BlockMetadata {
	int id;
	std::string group_id;
	std::string file_path;
	size_t start_byte;
	size_t end_byte;
	std::string orig_name;
	std::string mangled_name;
};

struct CommentNodeInfo {
	TSNode node;
	size_t start_byte;
	size_t end_byte;
};

std::string read_file(const std::string &path);

void write_file(const std::string &path, const std::string &content);

void collect_comments(TSNode node, const std::string &source, std::vector<CommentNodeInfo> &comments);

const std::vector<LanguageSpec> &language_registry();

// nullptr if no registered language claims this extension
const LanguageSpec *language_for_extension(const std::string &extension);

TSNode get_associated_function_node(TSNode comment_node, const LanguageSpec &lang);

TSNode get_function_name_node(TSNode node, const LanguageSpec &lang);

void extract_blocks(const std::string &src_dir, const std::string &bundle_out, const std::string &map_out,
                     const std::string &target_group);

void inject_blocks(const std::string &bundle_in, const std::string &map_in);