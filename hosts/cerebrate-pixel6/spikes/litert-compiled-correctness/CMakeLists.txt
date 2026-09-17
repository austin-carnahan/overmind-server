cmake_minimum_required(VERSION 3.20)
project(litert_bench LANGUAGES CXX C)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_subdirectory("/tmp/litert_sdk/litert_cc_sdk" "/tmp/litert_sdk/litert_cc_sdk/build")
include_directories("/tmp/litert_sdk/litert_cc_sdk")

add_executable(litert_bench main.cc)
target_link_libraries(litert_bench litert_cc_api android log)
