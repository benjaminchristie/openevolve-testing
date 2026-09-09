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

// Everything the bundler needs to know about one language. Extending the
// bundler to a new language means adding one LanguageSpec (see
// LANGUAGE_REGISTRY in main.cpp) and its grammar to CMakeLists.txt -- nothing
// else in the extraction/injection logic is language-specific.
struct LanguageSpec {
	std::string name;
	std::vector<std::string> extensions;
	const TSLanguage *(*get_language)();
	// Line-comment token for this language ("//" for C/C++, "#" for Python).
	// Used for the bundle's own EVOLVE-BLOCK-START/END markers and per-block
	// delimiters, so the generated bundle stays syntactically valid source in
	// its own language rather than always emitting C-style "//" comments.
	std::string line_comment_prefix;
	// Node type(s) that count as an evolvable block, e.g. {"function_definition"}.
	std::vector<std::string> block_node_types;
	// Node type(s) that wrap a block and should be captured along with it,
	// e.g. C++ template_declaration or Python's decorator wrapper.
	std::vector<std::string> wrapper_node_types;
	// Fallback path only (see get_function_name_node): child node types not to
	// recurse into while hunting for a name, for grammars where the block
	// node has no direct "name" field (e.g. C/C++ function pointer/template
	// return types nest the identifier inside a declarator chain).
	std::vector<std::string> name_search_skip_types;
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

// Returns nullptr if no registered language claims this extension (the file
// is skipped rather than treated as an error, so a src_dir can freely contain
// non-source files).
const LanguageSpec *language_for_extension(const std::string &extension);

TSNode get_associated_function_node(TSNode comment_node, const LanguageSpec &lang);

TSNode get_function_name_node(TSNode node, const LanguageSpec &lang);

void extract_blocks(const std::string &src_dir, const std::string &bundle_out, const std::string &map_out,
                     const std::string &target_group);

void inject_blocks(const std::string &bundle_in, const std::string &map_in);