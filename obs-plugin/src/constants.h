#pragma once

#define PLUGIN_VERSION "\nVersion: 0.3.0"
#define PLUGIN_AUTHOR "Author: Davi Be"
#define GITHUB_URL "https://github.com/DaviBe92/AutoSplit64plus"
#define DISCORD_URL "https://discord.gg/VmrQQBpPSK"

/*
 * Name of the shared-memory segment the plugin writes frames into and the
 * AutoSplit64 Python side reads from. The two must agree exactly.
 *
 * Windows: a CreateFileMapping tag name ("as64_grabber").
 * POSIX:   a shm_open name; it must begin with a single '/' and, on Linux,
 *          appears to readers as the file /dev/shm/as64_grabber.
 */
#ifdef _WIN32
#define AS64_SHMEM_NAME TEXT("as64_grabber")
#else
#define AS64_SHMEM_NAME "/as64_grabber"
#endif
