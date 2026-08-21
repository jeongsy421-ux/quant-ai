"""
==============================================
PERSONAL FINANCE - 다운로드 폴더 감시 자동 임포트
==============================================
은행/카드사에서 내려받은 거래내역 파일을 지정 폴더에 넣어두기만 하면
자동으로 읽어 DB에 적재하고 처리 완료 폴더로 옮긴다.

  python -m backend.finance.cli watch --dir ~/Downloads/finance --interval 300
"""
from __future__ import annotations

import os
import shutil
import time
from typing import Any, Optional

SUPPORTED = (".csv", ".tsv", ".txt", ".xlsx")


def scan_once(db, watch_dir: str, archive_dir: Optional[str] = None) -> dict[str, Any]:
    """폴더를 1회 스캔하여 새 파일을 임포트"""
    from .csv_importer import import_paths

    watch_dir = os.path.expanduser(watch_dir)
    os.makedirs(watch_dir, exist_ok=True)
    archive_dir = os.path.expanduser(archive_dir or os.path.join(watch_dir, "_imported"))

    targets = [
        os.path.join(watch_dir, f)
        for f in sorted(os.listdir(watch_dir))
        if f.lower().endswith(SUPPORTED) and not f.startswith(".")
        and os.path.isfile(os.path.join(watch_dir, f))
    ]
    if not targets:
        return {"inserted": 0, "duplicated": 0, "files": []}

    result = import_paths(db, targets)

    os.makedirs(archive_dir, exist_ok=True)
    for path in targets:
        dest = os.path.join(archive_dir, os.path.basename(path))
        if os.path.exists(dest):
            base, ext = os.path.splitext(dest)
            dest = f"{base}_{int(time.time())}{ext}"
        shutil.move(path, dest)
    result["archived_to"] = archive_dir
    return result


def watch(db, watch_dir: str, interval: int = 300, archive_dir: Optional[str] = None) -> None:
    """폴더를 주기적으로 감시 (Ctrl+C로 종료)"""
    print(f"[watch] {os.path.expanduser(watch_dir)} 감시 시작 ({interval}초 주기)")
    while True:
        try:
            res = scan_once(db, watch_dir, archive_dir)
            if res["inserted"] or res["duplicated"]:
                print(f"[watch] 신규 {res['inserted']}건 / 중복 {res['duplicated']}건")
        except KeyboardInterrupt:
            print("[watch] 종료")
            return
        except Exception as e:
            print(f"[watch] 오류: {e}")
        time.sleep(interval)
