cmake_minimum_required(VERSION 3.16)
project(bundler CXX C)

if(POLICY CMP0135)
    cmake_policy(SET CMP0135 NEW)
endif()

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)

include(FetchContent)

FetchContent_Declare(
    json
    URL https://github.com/nlohmann/json/releases/download/v3.11.3/json.tar.xz
)
FetchContent_MakeAvailable(json)

FetchContent_Declare(
    tree-sitter
    GIT_REPOSITORY https://github.com/tree-sitter/tree-sitter.git
    GIT_TAG        v0.22.6
    GIT_PROGRESS   TRUE
)
FetchContent_GetProperties(tree-sitter)
if(NOT tree-sitter_POPULATED)
    FetchContent_Populate(tree-sitter)
    add_library(tree-sitter STATIC
        ${tree-sitter_SOURCE_DIR}/lib/src/lib.c
    )
    target_include_directories(tree-sitter PUBLIC
        ${tree-sitter_SOURCE_DIR}/lib/include
        ${tree-sitter_SOURCE_DIR}/lib/src
    )
endif()

# Adds one tree-sitter grammar as a static library named tree-sitter-<lang>.
# Each grammar's src/ directory ships parser.c always, and scanner.c only when
# the language needs an external scanner (e.g. Python's indentation-sensitive
# tokens) -- the EXISTS check below handles both without per-language cases.
function(add_tree_sitter_grammar lang repo tag)
    FetchContent_Declare(
        tree-sitter-${lang}
        GIT_REPOSITORY ${repo}
        GIT_TAG        ${tag}
        GIT_PROGRESS   TRUE
    )
    FetchContent_GetProperties(tree-sitter-${lang})
    if(NOT tree-sitter-${lang}_POPULATED)
        FetchContent_Populate(tree-sitter-${lang})
    endif()
    set(_src ${tree-sitter-${lang}_SOURCE_DIR}/src)
    set(_sources ${_src}/parser.c)
    if(EXISTS ${_src}/scanner.c)
        list(APPEND _sources ${_src}/scanner.c)
    endif()
    add_library(tree-sitter-${lang} STATIC ${_sources})
    target_include_directories(tree-sitter-${lang} PUBLIC ${_src})
    target_link_libraries(tree-sitter-${lang} PRIVATE tree-sitter)
    set(tree-sitter-${lang}_SOURCE_DIR ${tree-sitter-${lang}_SOURCE_DIR} PARENT_SCOPE)
endfunction()

# Language registry: add a new grammar here (and to LANGUAGE_REGISTRY in
# bundler.hpp) to extend the bundler to another language. See
# bundler/include/bundler/languages.hpp for how each grammar is mapped to file
# extensions and evolve-target node types.
add_tree_sitter_grammar(cpp    https://github.com/tree-sitter/tree-sitter-cpp.git    v0.22.0)
add_tree_sitter_grammar(c      https://github.com/tree-sitter/tree-sitter-c.git      v0.21.4)
add_tree_sitter_grammar(python https://github.com/tree-sitter/tree-sitter-python.git v0.21.0)

add_executable(bundler
    src/main.cpp
    # src/extractor.cpp
    # src/injector.cpp
)

target_include_directories(bundler PRIVATE
    ${tree-sitter_SOURCE_DIR}/lib/include include
)

target_link_libraries(bundler PRIVATE
    tree-sitter
    tree-sitter-cpp
    tree-sitter-c
    tree-sitter-python
    nlohmann_json::nlohmann_json
)