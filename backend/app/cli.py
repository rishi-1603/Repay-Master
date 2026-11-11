"""Operator commands. Run inside the API or worker container, or with DATABASE_URL set.

    python -m app.cli grant-role <username> <ops|admin>
    python -m app.cli revoke-role <username> <ops|admin>

This is how the first admin is created: there is no role-granting endpoint an unprivileged
caller can reach, and the grant is recorded in the database, not in an environment variable.
"""
import argparse
import sys

from app.db.base import session_factory
from app.services import roles


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("grant-role", "revoke-role"):
        p = sub.add_parser(name)
        p.add_argument("username")
        p.add_argument("role", choices=roles.ROLES)
    args = parser.parse_args(argv)

    with session_factory()() as session:
        if args.command == "grant-role":
            changed = roles.grant(session, args.username, args.role, actor="cli")
            print(f"granted {args.role} to {args.username}" if changed else f"{args.username} already has {args.role}")
        else:
            changed = roles.revoke(session, args.username, args.role, actor="cli")
            print(f"revoked {args.role} from {args.username}" if changed else f"{args.username} does not have {args.role}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
