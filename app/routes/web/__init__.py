# SPDX-License-Identifier: AGPL-3.0-or-later
from fastapi import APIRouter

from . import account, admin, auth, receipts

router = APIRouter(include_in_schema=False)
router.include_router(auth.router)
router.include_router(receipts.router)
router.include_router(account.router)
router.include_router(admin.router)
