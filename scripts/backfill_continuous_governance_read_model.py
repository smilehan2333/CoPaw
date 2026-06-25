# -*- coding: utf-8 -*-
"""执行持续治理数据库读模型历史回填。"""

import argparse
import asyncio
import sys
from pathlib import Path

project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from swe.app.continuous_governance.backfill import (  # noqa: E402
    backfill_continuous_governance_source,
)
from swe.app.continuous_governance.store import (  # noqa: E402
    ContinuousGovernanceStore,
)
from swe.app.workspace.tenant_init_source_store import (  # noqa: E402
    init_tenant_init_source_module,
    get_tenant_init_source_store,
)
from swe.database.config import get_database_config  # noqa: E402
from swe.database.connection import DatabaseConnection  # noqa: E402


async def _run() -> None:
    """连接数据库并执行指定 source 的历史回填。"""
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace-root", required=True)
    parser.add_argument("--source-id", required=True)
    args = parser.parse_args()

    db = DatabaseConnection(get_database_config())
    await db.connect()
    try:
        init_tenant_init_source_module(db)
        tenant_store = get_tenant_init_source_store()
        if tenant_store is None:
            raise RuntimeError("tenant init source store is unavailable")
        tenants = await tenant_store.get_by_source(args.source_id)
        counts = await backfill_continuous_governance_source(
            ContinuousGovernanceStore(db),
            workspace_root=Path(args.workspace_root),
            source_id=args.source_id,
            tenants=list(tenants),
        )
        print(counts)
    finally:
        await db.close()


if __name__ == "__main__":
    asyncio.run(_run())
