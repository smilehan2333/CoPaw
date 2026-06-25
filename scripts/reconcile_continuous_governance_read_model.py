# -*- coding: utf-8 -*-
"""执行持续治理数据库读模型待对账项重放。"""

import argparse
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from swe.app.continuous_governance.service import (  # noqa: E402
    ContinuousGovernanceService,
)
from swe.app.continuous_governance.store import (  # noqa: E402
    ContinuousGovernanceStore,
)
from swe.database.config import get_database_config  # noqa: E402
from swe.database.connection import DatabaseConnection  # noqa: E402


async def _run() -> None:
    """连接数据库并重放指定 source 的待对账 health 项。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--source-id", required=True)
    parser.add_argument(
        "--entity-id",
        action="append",
        dest="entity_ids",
        help="只重放指定 entity_id；可重复传入。",
    )
    args = parser.parse_args()

    db = DatabaseConnection(get_database_config())
    await db.connect()
    try:
        service = ContinuousGovernanceService(
            ContinuousGovernanceStore(db),
        )
        result = await service.reconcile_health(
            source_id=args.source_id,
            entity_ids=set(args.entity_ids) if args.entity_ids else None,
        )
        print(result)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(_run())
