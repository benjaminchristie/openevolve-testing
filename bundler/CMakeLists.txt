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

FetchContent_Declare(
    tree-sitter-cpp
    GIT_REPOSITORY https://github.com/tree-sitter/tree-sitter-cpp.git
    GIT_TAG        v0.22.0
    GIT_PROGRESS   TRUE
)
FetchContent_GetProperties(tree-sitter-cpp)
if(NOT tree-sitter-cpp_POPULATED)
    FetchContent_Populate(tree-sitter-cpp)
    add_library(tree-sitter-cpp STATIC
        ${tree-sitter-cpp_SOURCE_DIR}/src/parser.c
        ${tree-sitter-cpp_SOURCE_DIR}/src/scanner.c
    )
    target_include_directories(tree-sitter-cpp PUBLIC ${tree-sitter-cpp_SOURCE_DIR}/src)
    target_link_libraries(tree-sitter-cpp PRIVATE tree-sitter)
endif()

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
    nlohmann_json::nlohmann_json
)