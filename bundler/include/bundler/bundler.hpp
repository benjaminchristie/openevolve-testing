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

TSNode get_associated_function_node(TSNode comment_node);

TSNode get_function_name_node(TSNode node);

void extract_blocks(const std::string &src_dir, const std::string &bundle_out, const std::string &map_out);

void inject_blocks(const std::string &bundle_in, const std::string &map_in);