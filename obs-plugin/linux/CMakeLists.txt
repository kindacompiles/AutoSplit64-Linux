# Standalone Linux build for the AutoSplit64+ OBS frame-grabber plugin.
#
# The base repo's top-level CMake (obs-plugintemplate) only ships Windows
# platform modules (cmake/windows). Rather than vendor the whole template's
# Linux module set, this is a small self-contained build that finds libobs
# through pkg-config and produces `autosplit64plus-framegrabber.so`.
#
#   cmake -S obs-plugin/linux -B obs-plugin/linux/build -DCMAKE_BUILD_TYPE=Release
#   cmake --build obs-plugin/linux/build
#
# Requires: cmake (>=3.16), a C compiler, and OBS headers/libs
#   Debian/Ubuntu : sudo apt install libobs-dev
#   Fedora        : sudo dnf install obs-studio-devel
#   Arch          : the `obs-studio` package ships the headers
#
# See linux/README.md for where to install the resulting .so.

cmake_minimum_required(VERSION 3.16)
project(autosplit64plus-framegrabber C)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release CACHE STRING "" FORCE)
endif()

find_package(PkgConfig REQUIRED)
pkg_check_modules(LIBOBS REQUIRED libobs)

add_library(autosplit64plus-framegrabber MODULE
  ${CMAKE_CURRENT_SOURCE_DIR}/../src/autosplit64plus-framegrabber.c
)

target_include_directories(autosplit64plus-framegrabber PRIVATE
  ${CMAKE_CURRENT_SOURCE_DIR}/../src
  ${LIBOBS_INCLUDE_DIRS}
)

target_link_directories(autosplit64plus-framegrabber PRIVATE ${LIBOBS_LIBRARY_DIRS})

# librt provides shm_open/shm_unlink on glibc < 2.34; harmless to link on newer.
target_link_libraries(autosplit64plus-framegrabber PRIVATE ${LIBOBS_LIBRARIES} rt)

# OBS loads the module by file name; it must not carry the default "lib" prefix.
set_target_properties(autosplit64plus-framegrabber PROPERTIES PREFIX "")

target_compile_options(autosplit64plus-framegrabber PRIVATE -Wall -Wextra)
