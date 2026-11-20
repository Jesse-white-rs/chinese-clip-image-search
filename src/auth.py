"""认证与用户管理模块。

提供：users 表初始化、密码哈希、JWT 签发/校验、登录认证、当前用户依赖、
以及供 admin 使用的用户增删改查。密码使用 bcrypt 加盐哈希，绝不存明文。
"""
import time
import threading
from typing import Optional

import pymysql
from jose import JWTError, jwt
import bcrypt
from fastapi import Depends, HTTPException, Header

from config import (
    MYSQL_HOST, MYSQL_PORT, MYSQL_USER, MYSQL_PWD, MYSQL_DB,
    JWT_SECRET, JWT_ALGORITHM, TOKEN_EXPIRE_DAYS, ADMIN_USER, ADMIN_PASSWORD,
)
from logs import LOGGER

def hash_password(password: str) -> str:
    """bcrypt 加盐哈希，返回字符串。兼容 passlib 生成的旧哈希格式。"""
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """校验密码。bcrypt.checkpw 可直接验证 passlib 生成的标准 bcrypt 哈希。"""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


class UserStore:
    """用户表存储：独立连接，提供用户 CRUD 与初始管理员初始化。"""

    def __init__(self):
        self.conn = None
        self.cursor = None
        self._last_ping = 0.0
        self._lock = threading.RLock()
        self._init_table()

    def _connect(self):
        self.conn = pymysql.connect(
            host=MYSQL_HOST, user=MYSQL_USER, port=MYSQL_PORT,
            password=MYSQL_PWD, database=MYSQL_DB,
            autocommit=True, connect_timeout=30, read_timeout=30, charset="utf8mb4",
        )
        self.cursor = self.conn.cursor()

    def _ensure_conn(self):
        now = time.time()
        if self.conn is None:
            self._connect()
            self._last_ping = now
        elif now - self._last_ping > 30:
            self.conn.ping(reconnect=True)
            self._last_ping = now

    def _init_table(self):
        """首次启动建表并创建初始管理员（幂等）。"""
        try:
            self._ensure_conn()
            self.cursor.execute(
                "CREATE TABLE IF NOT EXISTS users ("
                "id BIGINT AUTO_INCREMENT PRIMARY KEY, "
                "username VARCHAR(64) NOT NULL UNIQUE, "
                "password_hash VARCHAR(255) NOT NULL, "
                "role VARCHAR(16) NOT NULL DEFAULT 'user', "
                "is_active TINYINT(1) NOT NULL DEFAULT 1, "
                "created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, "
                "last_login DATETIME DEFAULT NULL"
                ") ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;"
            )
            self.cursor.execute("SELECT id FROM users WHERE username=%s", (ADMIN_USER,))
            if not self.cursor.fetchone():
                self.cursor.execute(
                    "INSERT INTO users (username, password_hash, role) VALUES (%s,%s,%s)",
                    (ADMIN_USER, hash_password(ADMIN_PASSWORD), "admin"),
                )
                LOGGER.info(f"已创建初始管理员账号: {ADMIN_USER}")
        except Exception as e:
            LOGGER.error(f"初始化用户表失败: {e}")
            raise

    @staticmethod
    def _row_to_dict(row):
        if not row:
            return None
        return {
            "id": row[0], "username": row[1], "role": row[2],
            "isActive": bool(row[3]),
            "createdAt": str(row[4]) if row[4] else None,
            "lastLogin": str(row[5]) if row[5] else None,
        }

    def get_by_username(self, username):
        self._ensure_conn()
        with self._lock:
            self.cursor.execute(
                "SELECT id,username,password_hash,role,is_active,created_at,last_login "
                "FROM users WHERE username=%s", (username,)
            )
            row = self.cursor.fetchone()
        if not row:
            return None
        # row: (id, username, password_hash, role, is_active, created_at, last_login)
        user = self._row_to_dict((row[0], row[1], row[3], row[4], row[5], row[6]))
        user["passwordHash"] = row[2]
        return user

    def get_by_id(self, user_id):
        self._ensure_conn()
        with self._lock:
            self.cursor.execute(
                "SELECT id,username,role,is_active,created_at,last_login FROM users WHERE id=%s",
                (int(user_id),)
            )
            return self._row_to_dict(self.cursor.fetchone())

    def list_users(self, page=1, size=10):
        self._ensure_conn()
        with self._lock:
            self.cursor.execute("SELECT COUNT(*) FROM users")
            total = self.cursor.fetchone()[0]
            self.cursor.execute(
                "SELECT id,username,role,is_active,created_at,last_login FROM users "
                "ORDER BY id LIMIT %s,%s", ((page - 1) * size, size)
            )
            rows = self.cursor.fetchall()
        return {
            "total": total, "totalPages": (total + size - 1) // size,
            "page": page, "size": size,
            "data": [self._row_to_dict(r) for r in rows],
        }

    def create(self, username, password, role="user"):
        self._ensure_conn()
        with self._lock:
            self.cursor.execute(
                "INSERT INTO users (username,password_hash,role) VALUES (%s,%s,%s)",
                (username, hash_password(password), role if role in ("admin", "user") else "user"),
            )
            return self.cursor.lastrowid

    def update(self, user_id, role=None, is_active=None):
        self._ensure_conn()
        fields, params = [], []
        if role is not None:
            fields.append("role=%s")
            params.append(role if role in ("admin", "user") else "user")
        if is_active is not None:
            fields.append("is_active=%s")
            params.append(1 if is_active else 0)
        if not fields:
            return False
        params.append(int(user_id))
        with self._lock:
            self.cursor.execute(f"UPDATE users SET {','.join(fields)} WHERE id=%s", params)
            return self.cursor.rowcount > 0

    def update_password(self, user_id, new_password):
        self._ensure_conn()
        with self._lock:
            self.cursor.execute(
                "UPDATE users SET password_hash=%s WHERE id=%s",
                (hash_password(new_password), int(user_id)),
            )
            return self.cursor.rowcount > 0

    def update_last_login(self, user_id):
        self._ensure_conn()
        with self._lock:
            self.cursor.execute("UPDATE users SET last_login=NOW() WHERE id=%s", (int(user_id),))

    def delete(self, user_id):
        self._ensure_conn()
        with self._lock:
            self.cursor.execute("DELETE FROM users WHERE id=%s", (int(user_id),))
            return self.cursor.rowcount > 0


# 模块级单例：导入时即建表并初始化管理员
USER_STORE = UserStore()


def create_access_token(user):
    """签发 JWT，有效期 TOKEN_EXPIRE_DAYS 天。"""
    expire = time.time() + TOKEN_EXPIRE_DAYS * 24 * 3600
    payload = {"sub": user["username"], "role": user["role"], "uid": user["id"], "exp": expire}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_token(token):
    """校验并解析 JWT，失败返回 None。"""
    try:
        return jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
    except JWTError:
        return None


def get_current_user(authorization: Optional[str] = Header(None)):
    """FastAPI 依赖：从 Authorization: Bearer <token> 解析当前用户。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="未提供有效的认证令牌")
    payload = decode_token(authorization.split(" ", 1)[1])
    if not payload or not payload.get("sub"):
        raise HTTPException(status_code=401, detail="令牌无效或已过期")
    user = USER_STORE.get_by_username(payload["sub"])
    if not user or not user.get("isActive"):
        raise HTTPException(status_code=401, detail="用户不存在或已被禁用")
    return user


def get_current_admin(user=Depends(get_current_user)):
    """FastAPI 依赖：仅 admin 角色可访问。"""
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
