-- Auto-run by the postgres container on first boot (docker-entrypoint-initdb.d).
-- Creates the throwaway database the test suite points MONDAY_TEST_DSN at.
CREATE DATABASE monday_test;
