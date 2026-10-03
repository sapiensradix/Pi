// Copyright (c) 2019-2021 The Pi Core developers
// Distributed under the MIT software license, see the accompanying
// file COPYING or http://www.opensource.org/licenses/mit-license.php.
//
#include <chainparams.h>
#include <test/util/setup_common.h>
#include <util/system.h>
#include <univalue.h>

#ifdef ENABLE_EXTERNAL_SIGNER
#if defined(__GNUC__)
// Boost 1.78 requires the following workaround.
// See: https://github.com/boostorg/process/issues/235
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wnarrowing"
#endif
#include <boost/process.hpp>
#if defined(__GNUC__)
#pragma GCC diagnostic pop
#endif
#endif // ENABLE_EXTERNAL_SIGNER

#include <boost/test/unit_test.hpp>

BOOST_FIXTURE_TEST_SUITE(system_tests, BasicTestingSetup)

// At least one test is required (in case ENABLE_EXTERNAL_SIGNER is not defined).
// Workaround for https://github.com/bitcoin/bitcoin/issues/19128
BOOST_AUTO_TEST_CASE(dummy)
{
    BOOST_CHECK(true);
}

BOOST_AUTO_TEST_CASE(default_datadir_and_config_identity)
{
    const fs::path unix_home{"/home/pi-user"};
    const fs::path macos_home{"/Users/pi-user"};
    const fs::path windows_appdata{"C:/Users/pi-user/AppData/Roaming"};

    BOOST_CHECK_EQUAL(
        GetDefaultDataDirForPlatform(DefaultDataDirPlatform::UNIX_LIKE, unix_home),
        unix_home / ".pi");
    BOOST_CHECK_EQUAL(
        GetDefaultDataDirForPlatform(DefaultDataDirPlatform::MACOS, macos_home),
        macos_home / "Library/Application Support/Pi");
    BOOST_CHECK_EQUAL(
        GetDefaultDataDirForPlatform(DefaultDataDirPlatform::WINDOWS, {}, windows_appdata),
        windows_appdata / "Pi");

    BOOST_CHECK(
        GetDefaultDataDirForPlatform(DefaultDataDirPlatform::UNIX_LIKE, unix_home) !=
        unix_home / ".bitcoin");
    BOOST_CHECK(
        GetDefaultDataDirForPlatform(DefaultDataDirPlatform::MACOS, macos_home) !=
        macos_home / "Library/Application Support/Bitcoin");
    BOOST_CHECK(
        GetDefaultDataDirForPlatform(DefaultDataDirPlatform::WINDOWS, {}, windows_appdata) !=
        windows_appdata / "Bitcoin");

    BOOST_CHECK_EQUAL(PI_CONF_FILENAME, "pi.conf");
    BOOST_CHECK_NE(PI_CONF_FILENAME, "bitcoin.conf");
}

BOOST_AUTO_TEST_CASE(checkpoint_height)
{
    CCheckpointData checkpoints;
    BOOST_CHECK_EQUAL(checkpoints.GetHeight(), 0);

    checkpoints.mapCheckpoints.emplace(0, uint256{});
    checkpoints.mapCheckpoints.emplace(42, uint256{});
    BOOST_CHECK_EQUAL(checkpoints.GetHeight(), 42);
}

#ifdef ENABLE_EXTERNAL_SIGNER

BOOST_AUTO_TEST_CASE(run_command)
{
    {
        const UniValue result = RunCommandParseJSON("");
        BOOST_CHECK(result.isNull());
    }
    {
#ifdef WIN32
        const UniValue result = RunCommandParseJSON("cmd.exe /c echo {\"success\": true}");
#else
        const UniValue result = RunCommandParseJSON("echo \"{\"success\": true}\"");
#endif
        BOOST_CHECK(result.isObject());
        const UniValue& success = find_value(result, "success");
        BOOST_CHECK(!success.isNull());
        BOOST_CHECK_EQUAL(success.getBool(), true);
    }
    {
        // An invalid command is handled by Boost
#ifdef WIN32
        const std::string expected{"The system cannot find the file specified."};
#else
        const std::string expected{"No such file or directory"};
#endif
        BOOST_CHECK_EXCEPTION(RunCommandParseJSON("invalid_command"), boost::process::process_error, [&](const boost::process::process_error& e) {
            const std::string what(e.what());
            BOOST_CHECK(what.find("RunCommandParseJSON error:") == std::string::npos);
            BOOST_CHECK(what.find(expected) != std::string::npos);
            return true;
        });
    }
    {
        // Return non-zero exit code, no output to stderr
#ifdef WIN32
        const std::string command{"cmd.exe /c call"};
#else
        const std::string command{"false"};
#endif
        BOOST_CHECK_EXCEPTION(RunCommandParseJSON(command), std::runtime_error, [&](const std::runtime_error& e) {
            BOOST_CHECK(std::string(e.what()).find(strprintf("RunCommandParseJSON error: process(%s) returned 1: \n", command)) != std::string::npos);
            return true;
        });
    }
    {
        // Return non-zero exit code, with error message for stderr
#ifdef WIN32
        const std::string command{"cmd.exe /c dir nosuchfile"};
        const std::string expected{"File Not Found"};
#else
        const std::string command{"ls nosuchfile"};
        const std::string expected{"No such file or directory"};
#endif
        BOOST_CHECK_EXCEPTION(RunCommandParseJSON(command), std::runtime_error, [&](const std::runtime_error& e) {
            const std::string what(e.what());
            BOOST_CHECK(what.find(strprintf("RunCommandParseJSON error: process(%s) returned", command)) != std::string::npos);
            BOOST_CHECK(what.find(expected) != std::string::npos);
            return true;
        });
    }
    {
        BOOST_REQUIRE_THROW(RunCommandParseJSON("echo \"{\""), std::runtime_error); // Unable to parse JSON
    }
    // Test std::in, except for Windows
#ifndef WIN32
    {
        const UniValue result = RunCommandParseJSON("cat", "{\"success\": true}");
        BOOST_CHECK(result.isObject());
        const UniValue& success = find_value(result, "success");
        BOOST_CHECK(!success.isNull());
        BOOST_CHECK_EQUAL(success.getBool(), true);
    }
#endif
}
#endif // ENABLE_EXTERNAL_SIGNER

BOOST_AUTO_TEST_SUITE_END()
