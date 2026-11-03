"""Check native evidence guard against corruption and source-identity substitution."""
import os

from p7_angle_aggregate import SOURCE, read_lane


def main():
    lane, _, _ = read_lane(0, 1.)
    relative = next(iter(lane["cases"][0]["native_files"]))
    path = SOURCE / "angle-lane-0" / relative
    original = path.read_bytes()
    try:
        path.write_bytes(original + b"corrupt")
        try:
            read_lane(0, 1.)
        except AssertionError:
            print("corrupt native file rejected", flush=True)
        else:
            raise AssertionError("corruption was accepted")
    finally:
        path.write_bytes(original)
    sha = os.environ["ANGLE_SOURCE_COMMIT"]
    try:
        os.environ["ANGLE_SOURCE_COMMIT"] = "0"*40
        try:
            read_lane(0, 1.)
        except AssertionError:
            print("wrong source commit rejected", flush=True)
        else:
            raise AssertionError("wrong source was accepted")
    finally:
        os.environ["ANGLE_SOURCE_COMMIT"] = sha
    read_lane(0, 1.)
    print("restored evidence accepted", flush=True)


if __name__ == "__main__":
    main()
