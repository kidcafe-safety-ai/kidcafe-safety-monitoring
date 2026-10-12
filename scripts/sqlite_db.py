"""Backend SQLite DB 백업·복원·초기화 (Final Phase).

대상 DB는 API와 같은 규칙으로 정한다: `KIDCAFE_DB_PATH`가 있으면 그 경로,
없으면 `outputs/kidcafe_events.db`. Docker Compose는 `./outputs`를 volume으로
쓰므로 host에서 이 스크립트를 실행하면 컨테이너 DB를 그대로 다룬다.
표준 라이브러리만 사용한다.

    python scripts/sqlite_db.py backup
    python scripts/sqlite_db.py backup --dest-dir outputs/backups
    python scripts/sqlite_db.py restore outputs/backups/kidcafe_events_20261012_101500.db --yes
    python scripts/sqlite_db.py reset --yes

- backup: SQLite online backup API로 복사한다. API가 실행 중이어도 일관된
  사본이 만들어진다.
- restore: 현재 DB를 먼저 백업한 뒤 지정한 백업 내용으로 덮어쓴다.
- reset: 현재 DB를 먼저 백업한 뒤 events·current_status를 비운 새 DB를 만든다.

restore·reset은 데이터를 바꾸므로 `--yes`가 있어야 실행된다. Vision AI 전송을
멈춘 상태에서 실행한다. API는 재시작하지 않아도 다음 요청부터 새 DB를 쓴다.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.api.database import get_db_path, get_project_root, init_db  # noqa: E402

REQUIRED_TABLES = ("events", "current_status")


def default_backup_dir() -> Path:
    return get_project_root() / "outputs" / "backups"


def _copy_database(source: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(source)
    try:
        dest_conn = sqlite3.connect(dest)
        try:
            src_conn.backup(dest_conn)
        finally:
            dest_conn.close()
    finally:
        src_conn.close()


def _table_names(path: Path) -> List[str]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return [
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        ]
    finally:
        conn.close()


def count_rows(path: Path) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return {
            table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in REQUIRED_TABLES
        }
    finally:
        conn.close()


def backup(db_path: Path, dest_dir: Path, now: Optional[datetime] = None) -> Path:
    if not db_path.is_file():
        raise FileNotFoundError(f"DB 파일이 없습니다: {db_path}")
    stamp = (now or datetime.now()).strftime("%Y%m%d_%H%M%S")
    dest = dest_dir / f"{db_path.stem}_{stamp}{db_path.suffix}"
    suffix = 1
    while dest.exists():
        dest = dest_dir / f"{db_path.stem}_{stamp}_{suffix}{db_path.suffix}"
        suffix += 1
    _copy_database(db_path, dest)
    return dest


def restore(backup_path: Path, db_path: Path, dest_dir: Path) -> Optional[Path]:
    if not backup_path.is_file():
        raise FileNotFoundError(f"백업 파일이 없습니다: {backup_path}")
    missing = [table for table in REQUIRED_TABLES if table not in _table_names(backup_path)]
    if missing:
        raise ValueError(f"KidCafe DB 백업이 아닙니다 (누락 테이블: {missing})")

    previous = backup(db_path, dest_dir) if db_path.is_file() else None
    _copy_database(backup_path, db_path)
    init_db()  # 오래된 백업이면 Phase 3 컬럼 migration을 적용한다.
    return previous


def reset(db_path: Path, dest_dir: Path) -> Optional[Path]:
    previous = backup(db_path, dest_dir) if db_path.is_file() else None
    db_path.parent.mkdir(parents=True, exist_ok=True)
    init_db()
    conn = sqlite3.connect(db_path)
    try:
        with conn:
            for table in REQUIRED_TABLES:
                conn.execute(f"DELETE FROM {table}")
            # AUTOINCREMENT id를 1부터 다시 시작한다.
            conn.execute("DELETE FROM sqlite_sequence WHERE name = 'events'")
        conn.execute("VACUUM")
    finally:
        conn.close()
    return previous


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="KidCafe SQLite 백업·복원·초기화")
    parser.add_argument(
        "--dest-dir",
        type=Path,
        default=None,
        help="백업 저장 폴더 (기본: outputs/backups)",
    )
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("backup", help="현재 DB를 백업한다")
    restore_parser = sub.add_parser("restore", help="백업으로 현재 DB를 덮어쓴다")
    restore_parser.add_argument("backup_path", type=Path)
    restore_parser.add_argument("--yes", action="store_true")
    reset_parser = sub.add_parser("reset", help="백업 후 DB를 비운다")
    reset_parser.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)

    db_path = get_db_path()
    dest_dir = args.dest_dir or default_backup_dir()

    try:
        if args.command == "backup":
            dest = backup(db_path, dest_dir)
            print(f"백업 완료: {db_path} -> {dest}  {count_rows(dest)}")
            return 0

        if not args.yes:
            print(f"{args.command}는 DB 내용을 바꿉니다. 확인했다면 --yes를 붙이세요: {db_path}")
            return 2

        if args.command == "restore":
            previous = restore(args.backup_path, db_path, dest_dir)
            action = f"복원 완료: {args.backup_path} -> {db_path}"
        else:
            previous = reset(db_path, dest_dir)
            action = f"초기화 완료: {db_path}"
        if previous:
            print(f"기존 DB 백업: {previous}")
        print(f"{action}  {count_rows(db_path)}")
        return 0
    except (FileNotFoundError, ValueError, sqlite3.DatabaseError) as exc:
        print(f"실패: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
