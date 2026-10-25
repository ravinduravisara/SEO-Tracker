from __future__ import annotations

import os
import re
import logging
from datetime import datetime
from typing import Any, Optional, List, Dict, Union

logger = logging.getLogger("esupport_db")

# Database URI: defaults to local SQLite; MongoDB Atlas or PostgreSQL can be configured via DATABASE_URL env var
DEFAULT_SQLITE_URI = "sqlite:///./seo_platform.db"
DB_PATH = os.getenv("DATABASE_URL", DEFAULT_SQLITE_URI).strip()

IS_MONGO = DB_PATH.startswith("mongodb://") or DB_PATH.startswith("mongodb+srv://")

# -----------------------------------------------------------------------------
# MONGODB IMPLEMENTATION (NATIVE NOSQL ADAPTER & ODM)
# -----------------------------------------------------------------------------
if IS_MONGO:
    # Ensure public DNS nameservers are used for resolving MongoDB Atlas SRV records
    # and shard A records. This prevents NXDOMAIN and [Errno 8] failures on cellular hotspots and local DNS.
    import socket
    try:
        import dns.resolver
        _custom_resolver = dns.resolver.Resolver(configure=False)
        _custom_resolver.nameservers = ["8.8.8.8", "1.1.1.1", "8.8.4.4"]
        _custom_resolver.timeout = 5.0
        _custom_resolver.lifetime = 10.0
        dns.resolver.default_resolver = _custom_resolver

        _orig_getaddrinfo = socket.getaddrinfo
        def _resilient_getaddrinfo(host, port, family=0, type=0, proto=0, flags=0):
            try:
                return _orig_getaddrinfo(host, port, family, type, proto, flags)
            except socket.gaierror as orig_exc:
                try:
                    ans = _custom_resolver.resolve(host, "A")
                    ip = str(ans[0])
                    return _orig_getaddrinfo(ip, port, family, type, proto, flags)
                except Exception:
                    raise orig_exc
        socket.getaddrinfo = _resilient_getaddrinfo
    except Exception as _dns_err:
        logger.warning(f"Could not configure custom DNS resolver: {_dns_err}")

    import pymongo

    _mongo_client: Optional[pymongo.MongoClient] = None
    _mongo_db = None

    def get_mongo_client() -> pymongo.MongoClient:
        global _mongo_client
        if _mongo_client is None:
            _mongo_client = pymongo.MongoClient(
                DB_PATH,
                maxPoolSize=50,
                minPoolSize=5,
                maxIdleTimeMS=60000,
                serverSelectionTimeoutMS=10000,
                connectTimeoutMS=10000,
                socketTimeoutMS=45000,
                retryWrites=True
            )
        return _mongo_client

    def get_mongo_db():
        global _mongo_db
        if _mongo_db is None:
            client = get_mongo_client()
            parsed = pymongo.uri_parser.parse_uri(DB_PATH)
            db_name = parsed.get("database") or "seo_platform"
            _mongo_db = client[db_name]
        return _mongo_db

    class BinaryExpression:
        def __init__(self, field: str, op: str, value: Any):
            self.field = field
            self.op = op
            self.value = value

        def to_mongo(self) -> Dict[str, Any]:
            if self.op == "$eq":
                return {self.field: self.value}
            elif self.op == "$regex":
                return {self.field: {"$regex": self.value, "$options": "i"}}
            else:
                return {self.field: {self.op: self.value}}

    class OrderByExpression:
        def __init__(self, field: str, direction: int = 1):
            self.field = field
            self.direction = direction

    def desc(col: Any) -> OrderByExpression:
        if isinstance(col, OrderByExpression):
            return OrderByExpression(col.field, -1)
        if hasattr(col, "desc"):
            return col.desc()
        return OrderByExpression(str(col), -1)

    def asc(col: Any) -> OrderByExpression:
        if isinstance(col, OrderByExpression):
            return OrderByExpression(col.field, 1)
        if hasattr(col, "asc"):
            return col.asc()
        return OrderByExpression(str(col), 1)

    class Column:
        def __init__(self, type_=None, default=None, nullable=True, unique=False, index=False, primary_key=False, onupdate=None):
            self.type_ = type_
            self.default = default
            self.nullable = nullable
            self.unique = unique
            self.index = index
            self.primary_key = primary_key
            self.onupdate = onupdate
            self.name: Optional[str] = None

        def __set_name__(self, owner, name: str):
            self.name = name

        def __get__(self, instance, owner):
            if instance is None:
                return self
            if self.name in instance._data:
                return instance._data[self.name]
            val = self._eval_default()
            if val is not None:
                instance._data[self.name] = val
            return val

        def __set__(self, instance, value):
            instance._data[self.name] = value
            if hasattr(instance, "_session") and instance._session and getattr(instance, "_is_persisted", False):
                instance._session._dirty.add(instance)

        def _eval_default(self):
            if callable(self.default):
                return self.default()
            return self.default

        def __eq__(self, other):
            return BinaryExpression(self.name, "$eq", other)

        def __ne__(self, other):
            return BinaryExpression(self.name, "$ne", other)

        def __gt__(self, other):
            return BinaryExpression(self.name, "$gt", other)

        def __ge__(self, other):
            return BinaryExpression(self.name, "$gte", other)

        def __lt__(self, other):
            return BinaryExpression(self.name, "$lt", other)

        def __le__(self, other):
            return BinaryExpression(self.name, "$lte", other)

        def in_(self, values):
            return BinaryExpression(self.name, "$in", list(values))

        def like(self, pattern: str):
            escaped = re.escape(pattern).replace(r"\%", ".*").replace(r"\_", ".")
            return BinaryExpression(self.name, "$regex", f"^{escaped}$")

        def desc(self):
            return OrderByExpression(self.name, -1)

        def asc(self):
            return OrderByExpression(self.name, 1)

    # Type placeholders to match SQLAlchemy declarations
    class Integer: pass
    class Float: pass
    class DateTime: pass
    class ForeignKey:
        def __init__(self, target, **kwargs):
            self.target = target
    class Text:
        def with_variant(self, variant, dialect):
            return self
    class LONGTEXT: pass

    class String:
        def __init__(self, length=255, **kwargs):
            self.length = length

    _MODEL_REGISTRY: Dict[str, Any] = {}

    class MongoModelMeta(type):
        def __new__(mcls, name, bases, attrs):
            cls = super().__new__(mcls, name, bases, attrs)
            _MODEL_REGISTRY[name] = cls
            return cls

    class MongoModelBase(metaclass=MongoModelMeta):
        __tablename__ = ""

        def __init__(self, **kwargs):
            self._data = {}
            self._is_persisted = False
            self._session = None
            for k, v in kwargs.items():
                setattr(self, k, v)

        def to_dict(self):
            return dict(self._data)

        def _to_mongo_doc(self):
            doc = {}
            for col_name, col_obj in self.__class__.__dict__.items():
                if isinstance(col_obj, Column):
                    val = getattr(self, col_name)
                    doc[col_name] = val
            return doc

        def __repr__(self):
            return f"<{self.__class__.__name__} id={getattr(self, 'id', None)}>"

    class Relationship:
        def __init__(self, target_model_name: str, foreign_key=None, back_populates=None, cascade=None, order_by=None, is_list=None, **kwargs):
            self.target_model_name = target_model_name
            self.foreign_key = foreign_key or kwargs.get("foreign_keys")
            self.back_populates = back_populates
            self.cascade = cascade
            self.order_by = order_by
            self.is_list = is_list
            self.extra_kwargs = kwargs
            self.name: Optional[str] = None

        def __set_name__(self, owner, name: str):
            self.name = name

        def __set__(self, instance, value):
            if instance is not None and self.name:
                if not hasattr(instance, "_rel_cache"):
                    instance._rel_cache = {}
                instance._rel_cache[self.name] = value

        def _batch_load(self, siblings: list):
            """Eagerly resolve relationships across all sibling instances in a single bulk query (eliminates N+1)."""
            if not siblings:
                return
            target_cls = _MODEL_REGISTRY.get(self.target_model_name)
            if not target_cls:
                return

            session = None
            for s in siblings:
                if getattr(s, "_session", None):
                    session = s._session
                    break
            session = session or MongoSession._active_session or MongoSession()
            q = session.query(target_cls)

            from collections import defaultdict
            if self._is_list(siblings[0]):
                fk = self.foreign_key or f"{siblings[0].__tablename__.rstrip('s')}_id"
                if not hasattr(target_cls, fk):
                    if hasattr(target_cls, "client_id") and siblings[0].__tablename__ == "clients":
                        fk = "client_id"
                    elif hasattr(target_cls, "website_id") and siblings[0].__tablename__ == "websites":
                        fk = "website_id"
                    elif hasattr(target_cls, "lead_id") and siblings[0].__tablename__ == "seo_leads":
                        fk = "lead_id"
                    elif hasattr(target_cls, "audit_id") and siblings[0].__tablename__ == "audits":
                        fk = "audit_id"
                    elif hasattr(target_cls, "user_id") and siblings[0].__tablename__ == "admin_users":
                        fk = "user_id"
                    elif hasattr(target_cls, "invited_by_id") and siblings[0].__tablename__ == "admin_users":
                        fk = "invited_by_id"

                sibling_ids = [s.id for s in siblings if getattr(s, "id", None) is not None]
                if sibling_ids and hasattr(target_cls, fk):
                    res_q = q.filter(getattr(target_cls, fk).in_(sibling_ids))
                    if self.order_by:
                        res_q = res_q.order_by(self.order_by)
                    all_targets = res_q.all()
                    grouped = defaultdict(list)
                    for t in all_targets:
                        t_fk = getattr(t, fk, None)
                        if t_fk is not None:
                            grouped[t_fk].append(t)
                    for s in siblings:
                        if not hasattr(s, "_rel_cache"):
                            s._rel_cache = {}
                        s._rel_cache[self.name] = grouped.get(s.id, [])
            else:
                fk = self.foreign_key or f"{target_cls.__tablename__.rstrip('s')}_id"
                if not hasattr(siblings[0].__class__, fk):
                    if hasattr(siblings[0].__class__, "client_id") and target_cls.__tablename__ == "clients":
                        fk = "client_id"
                    elif hasattr(siblings[0].__class__, "website_id") and target_cls.__tablename__ == "websites":
                        fk = "website_id"
                    elif hasattr(siblings[0].__class__, "audit_id") and target_cls.__tablename__ == "audits":
                        fk = "audit_id"
                    elif hasattr(siblings[0].__class__, "admin_id") and target_cls.__tablename__ == "admin_users":
                        fk = "admin_id"
                    elif hasattr(siblings[0].__class__, "invited_by_id") and target_cls.__tablename__ == "admin_users":
                        fk = "invited_by_id"
                    elif hasattr(siblings[0].__class__, "lead_id") and target_cls.__tablename__ == "seo_leads":
                        fk = "lead_id"

                fks = list({getattr(s, fk, None) for s in siblings if getattr(s, fk, None) is not None})
                if fks and hasattr(target_cls, "id"):
                    all_targets = q.filter(target_cls.id.in_(fks)).all()
                    target_map = {getattr(t, "id"): t for t in all_targets}
                    for s in siblings:
                        if not hasattr(s, "_rel_cache"):
                            s._rel_cache = {}
                        s._rel_cache[self.name] = target_map.get(getattr(s, fk, None))

        def __get__(self, instance, owner):
            if instance is None:
                return self
            if not hasattr(instance, "_rel_cache"):
                instance._rel_cache = {}
            if self.name in instance._rel_cache:
                return instance._rel_cache[self.name]

            # Fast-path auto-batch preloading across siblings
            siblings = getattr(instance, "_siblings", None)
            if siblings and len(siblings) > 1:
                try:
                    self._batch_load(siblings)
                    if self.name in instance._rel_cache:
                        return instance._rel_cache[self.name]
                except Exception as b_err:
                    logger.debug(f"Auto-batch relationship load fallback: {b_err}")

            target_cls = _MODEL_REGISTRY.get(self.target_model_name)
            if not target_cls:
                return [] if self._is_list(instance) else None

            session = getattr(instance, "_session", None) or MongoSession._active_session or MongoSession()
            q = session.query(target_cls)

            if self._is_list(instance):
                fk = self.foreign_key or f"{instance.__tablename__.rstrip('s')}_id"
                if not hasattr(target_cls, fk):
                    if hasattr(target_cls, "client_id") and instance.__tablename__ == "clients":
                        fk = "client_id"
                    elif hasattr(target_cls, "website_id") and instance.__tablename__ == "websites":
                        fk = "website_id"
                    elif hasattr(target_cls, "lead_id") and instance.__tablename__ == "seo_leads":
                        fk = "lead_id"
                    elif hasattr(target_cls, "audit_id") and instance.__tablename__ == "audits":
                        fk = "audit_id"
                    elif hasattr(target_cls, "user_id") and instance.__tablename__ == "admin_users":
                        fk = "user_id"
                    elif hasattr(target_cls, "invited_by_id") and instance.__tablename__ == "admin_users":
                        fk = "invited_by_id"
                res = q.filter(getattr(target_cls, fk) == instance.id)
                if self.order_by:
                    res = res.order_by(self.order_by)
                val = res.all()
                instance._rel_cache[self.name] = val
                return val
            else:
                fk = self.foreign_key or f"{target_cls.__tablename__.rstrip('s')}_id"
                if not hasattr(instance.__class__, fk):
                    if hasattr(instance.__class__, "client_id") and target_cls.__tablename__ == "clients":
                        fk = "client_id"
                    elif hasattr(instance.__class__, "website_id") and target_cls.__tablename__ == "websites":
                        fk = "website_id"
                    elif hasattr(instance.__class__, "audit_id") and target_cls.__tablename__ == "audits":
                        fk = "audit_id"
                    elif hasattr(instance.__class__, "admin_id") and target_cls.__tablename__ == "admin_users":
                        fk = "admin_id"
                    elif hasattr(instance.__class__, "invited_by_id") and target_cls.__tablename__ == "admin_users":
                        fk = "invited_by_id"
                    elif hasattr(instance.__class__, "lead_id") and target_cls.__tablename__ == "seo_leads":
                        fk = "lead_id"
                fk_val = getattr(instance, fk, None)
                if fk_val is None:
                    return None
                val = q.filter(target_cls.id == fk_val).first()
                instance._rel_cache[self.name] = val
                return val

        def _is_list(self, instance) -> bool:
            if self.is_list is not None:
                return self.is_list
            singular = instance.__tablename__.rstrip("s")
            fk = f"{singular}_id"
            target_cls = _MODEL_REGISTRY.get(self.target_model_name)
            if target_cls and hasattr(target_cls, fk):
                return True
            if instance.__tablename__ == "admin_users" and self.target_model_name in ("ActivityLog", "TeamInvitation"):
                return True
            if instance.__tablename__ == "seo_leads" and self.target_model_name == "LeadNote":
                return True
            if instance.__tablename__ == "clients" and self.target_model_name in ("Website", "Audit", "PublicReport"):
                return True
            return False

    def relationship(target_model_name, **kwargs):
        return Relationship(target_model_name, **kwargs)

    class MongoQuery:
        def __init__(self, session, model_cls):
            self.session = session
            self.model_cls = model_cls
            self.filter_spec: Dict[str, Any] = {}
            self.sort_spec: List[tuple] = []
            self._offset = 0
            self._limit: Optional[int] = None
            self.projection: Optional[Dict[str, int]] = None

        def defer(self, *fields):
            if self.projection is None:
                self.projection = {}
            for f in fields:
                self.projection[f] = 0
            return self

        def only(self, *fields):
            if self.projection is None:
                self.projection = {"_id": 1}
            for f in fields:
                self.projection[f] = 1
            return self

        def filter(self, *criterion):
            for c in criterion:
                if isinstance(c, BinaryExpression):
                    m = c.to_mongo()
                    for k, v in m.items():
                        if k in self.filter_spec:
                            if "$and" not in self.filter_spec:
                                self.filter_spec = {"$and": [{k: self.filter_spec.pop(k)}]}
                            self.filter_spec["$and"].append({k: v})
                        else:
                            self.filter_spec[k] = v
                elif isinstance(c, dict):
                    self.filter_spec.update(c)
            return self

        def filter_by(self, **kwargs):
            for k, v in kwargs.items():
                self.filter_spec[k] = v
            return self

        def order_by(self, *criterion):
            for c in criterion:
                if isinstance(c, OrderByExpression):
                    self.sort_spec.append((c.field, c.direction))
                elif isinstance(c, Column):
                    self.sort_spec.append((c.name, 1))
                elif isinstance(c, str):
                    if c.startswith("desc(") and c.endswith(")"):
                        col = c[5:-1].split(".")[-1]
                        self.sort_spec.append((col, -1))
                    elif c.startswith("asc(") and c.endswith(")"):
                        col = c[4:-1].split(".")[-1]
                        self.sort_spec.append((col, 1))
                    else:
                        self.sort_spec.append((c, 1))
            return self

        def offset(self, n: int):
            self._offset = int(n or 0)
            return self

        def limit(self, n: int):
            self._limit = int(n) if n is not None else None
            return self

        def _get_collection(self):
            return get_mongo_db()[self.model_cls.__tablename__]

        def first(self):
            col = self._get_collection()
            kwargs = {"allow_disk_use": True}
            if self.projection:
                kwargs["projection"] = self.projection
            cur = col.find(self.filter_spec, **kwargs)
            if self.sort_spec:
                cur = cur.sort(self.sort_spec)
            if self._offset:
                cur = cur.skip(self._offset)
            doc = next(cur, None)
            if not doc:
                return None
            return self._doc_to_instance(doc)

        def prefetch(self, *relations):
            if not hasattr(self, "_prefetch_fields"):
                self._prefetch_fields = set()
            self._prefetch_fields.update(relations)
            return self

        def options(self, *args):
            # Compatibility helper for SQLAlchemy-style joinedload / selectinload
            return self

        def all(self):
            col = self._get_collection()
            kwargs = {"allow_disk_use": True}
            if self.projection:
                kwargs["projection"] = self.projection
            cur = col.find(self.filter_spec, **kwargs)
            if self.sort_spec:
                cur = cur.sort(self.sort_spec)
            if self._offset:
                cur = cur.skip(self._offset)
            if self._limit is not None:
                cur = cur.limit(self._limit)
            instances = [self._doc_to_instance(doc) for doc in cur]
            if len(instances) > 1:
                for inst in instances:
                    inst._siblings = instances
            if hasattr(self, "_prefetch_fields") and self._prefetch_fields and instances:
                for rel_name in self._prefetch_fields:
                    rel_attr = getattr(self.model_cls, rel_name, None)
                    if isinstance(rel_attr, Relationship):
                        rel_attr._batch_load(instances)
            return instances

        def count(self) -> int:
            col = self._get_collection()
            if not self.filter_spec:
                try:
                    return col.estimated_document_count()
                except Exception:
                    pass
            return col.count_documents(self.filter_spec)

        def delete(self) -> int:
            col = self._get_collection()
            res = col.delete_many(self.filter_spec)
            return res.deleted_count

        def _doc_to_instance(self, doc):
            doc.pop("_id", None)
            inst = self.model_cls()
            inst._data = doc
            inst._is_persisted = True
            inst._session = self.session
            return inst

    class MongoSession:
        _active_session = None

        def __init__(self):
            self._new = set()
            self._dirty = set()
            self._deleted = set()

        def query(self, model_cls):
            return MongoQuery(self, model_cls)

        def add(self, instance):
            instance._session = self
            self._new.add(instance)

        def delete(self, instance):
            if instance in self._new:
                self._new.remove(instance)
            else:
                self._deleted.add(instance)

        def refresh(self, instance):
            if not getattr(instance, "id", None):
                return
            col = get_mongo_db()[instance.__tablename__]
            doc = col.find_one({"id": instance.id})
            if doc:
                doc.pop("_id", None)
                instance._data.update(doc)

        def rollback(self):
            self._new.clear()
            self._dirty.clear()
            self._deleted.clear()

        def commit(self):
            db = get_mongo_db()

            # 1. Process inserts
            for inst in list(self._new):
                col = db[inst.__tablename__]
                if getattr(inst, "id", None) is None:
                    inst.id = self._get_next_id(inst.__tablename__)
                doc = inst._to_mongo_doc()
                col.replace_one({"id": inst.id}, doc, upsert=True)
                inst._is_persisted = True
            self._new.clear()

            # 2. Process updates
            for inst in list(self._dirty):
                if getattr(inst, "id", None) is not None:
                    for col_name, col_obj in inst.__class__.__dict__.items():
                        if isinstance(col_obj, Column) and col_obj.onupdate:
                            val = col_obj.onupdate() if callable(col_obj.onupdate) else col_obj.onupdate
                            setattr(inst, col_name, val)
                    col = db[inst.__tablename__]
                    doc = inst._to_mongo_doc()
                    col.replace_one({"id": inst.id}, doc, upsert=True)
            self._dirty.clear()

            # 3. Process deletes
            for inst in list(self._deleted):
                if getattr(inst, "id", None) is not None:
                    col = db[inst.__tablename__]
                    col.delete_one({"id": inst.id})
                    # Cascade deletes
                    if inst.__tablename__ == "clients":
                        db["websites"].delete_many({"client_id": inst.id})
                        db["audits"].delete_many({"client_id": inst.id})
                        db["public_reports"].delete_many({"client_id": inst.id})
                    elif inst.__tablename__ == "audits":
                        db["public_reports"].delete_many({"audit_id": inst.id})
                    elif inst.__tablename__ == "seo_leads":
                        db["lead_notes"].delete_many({"lead_id": inst.id})
            self._deleted.clear()

        def close(self):
            self.rollback()

        def __enter__(self):
            MongoSession._active_session = self
            return self

        def __exit__(self, exc_type, exc_val, exc_tb):
            if exc_type is not None:
                self.rollback()
            else:
                self.commit()
            MongoSession._active_session = None
            self.close()

        def _get_next_id(self, table_name: str) -> int:
            db = get_mongo_db()
            doc = db["_counters"].find_one_and_update(
                {"_id": table_name},
                {"$inc": {"seq": 1}},
                upsert=True,
                return_document=pymongo.ReturnDocument.AFTER
            )
            return doc["seq"]

    SessionLocal = MongoSession

    class _DummyMetadata:
        def create_all(self, bind=None):
            pass

    class _DummyEngine:
        url = DB_PATH
        class _BeginContext:
            def __enter__(self): return self
            def __exit__(self, exc_type, exc_val, exc_tb): pass
            def execute(self, stmt): pass
        def begin(self):
            return self._BeginContext()

    engine = _DummyEngine()

    class Base(MongoModelBase):
        metadata = _DummyMetadata()

# -----------------------------------------------------------------------------
# SQL / SQLALCHEMY IMPLEMENTATION (FALLBACK)
# -----------------------------------------------------------------------------
else:
    from sqlalchemy import create_engine, Column, Integer, String as _SQLAString, Float, DateTime, ForeignKey, Text, inspect, text
    from sqlalchemy.dialects.mysql import LONGTEXT
    from sqlalchemy.ext.declarative import declarative_base
    from sqlalchemy.orm import sessionmaker, relationship

    class String(_SQLAString):
        def __init__(self, length=255, **kwargs):
            super().__init__(length=length, **kwargs)

    if "sqlite" in DB_PATH:
        from sqlalchemy import event

        engine = create_engine(
            DB_PATH,
            connect_args={"check_same_thread": False, "timeout": 30.0},
        )

        @event.listens_for(engine, "connect")
        def set_sqlite_pragma(dbapi_connection, connection_record):
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.execute("PRAGMA synchronous=NORMAL")
            cursor.execute("PRAGMA busy_timeout=30000")
            cursor.close()
    else:
        engine = create_engine(DB_PATH)

    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base = declarative_base()


# -----------------------------------------------------------------------------
# MODELS (SHARED DECLARATIONS FOR MONGO & SQL)
# -----------------------------------------------------------------------------

class Client(Base):
    __tablename__ = "clients"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    company = Column(String)
    email = Column(String)
    phone = Column(String)
    status = Column(String, default="ACTIVE", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    websites = relationship("Website", back_populates="client", cascade="all, delete-orphan")
    audits = relationship("Audit", back_populates="client", cascade="all, delete-orphan")
    public_reports = relationship("PublicReport", back_populates="client")


class Website(Base):
    __tablename__ = "websites"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), index=True, nullable=True)
    url = Column(String, nullable=False)
    name = Column(String, default="")
    status = Column(String, default="ACTIVE", nullable=False)
    gsc_property = Column(String, default="")
    ga4_property_id = Column(String, default="")
    connection_status_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("Client", back_populates="websites")
    project = relationship("Project", back_populates="websites")
    audits = relationship("Audit", back_populates="website")
    public_reports = relationship("PublicReport", back_populates="website")


class Audit(Base):
    __tablename__ = "audits"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"))
    website_id = Column(Integer, ForeignKey("websites.id"), index=True)
    project_id = Column(Integer, ForeignKey("projects.id"), index=True, nullable=True)
    job_id = Column(String, unique=True, index=True)
    status = Column(String, default="COMPLETED", nullable=False)
    target_url = Column(String, nullable=False)
    result_json = Column(Text().with_variant(LONGTEXT, "mysql") if not IS_MONGO else Text, nullable=False)
    score = Column(Float)
    progress_json = Column(Text, default="{}", nullable=False)
    provenance_json = Column(Text, default="{}", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)

    client = relationship("Client", back_populates="audits")
    website = relationship("Website", back_populates="audits")
    project = relationship("Project")
    public_reports = relationship("PublicReport", back_populates="audit", cascade="all, delete-orphan")
    page_findings = relationship("PageFinding", back_populates="audit", cascade="all, delete-orphan")


class PublicReport(Base):
    __tablename__ = "public_reports"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    website_id = Column(Integer, ForeignKey("websites.id"), index=True)
    audit_id = Column(Integer, ForeignKey("audits.id"))
    token = Column(String, unique=True, index=True, nullable=False)
    status = Column(String, default="DRAFT")  # DRAFT, PUBLISHED, DISABLED
    snapshot_json = Column(Text().with_variant(LONGTEXT, "mysql") if not IS_MONGO else Text, default="{}", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    published_at = Column(DateTime)
    disabled_at = Column(DateTime)

    audit = relationship("Audit", back_populates="public_reports")
    client = relationship("Client", back_populates="public_reports")
    website = relationship("Website", back_populates="public_reports")


class AdminUser(Base):
    __tablename__ = "admin_users"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, unique=True, index=True, nullable=False)
    name = Column(String, default="")
    role = Column(String, default="SUPER_ADMIN", nullable=False)  # SUPER_ADMIN, ADMIN, SALES, SEO_ANALYST
    status = Column(String, default="ACTIVE", nullable=False)     # INVITED, ACTIVE, SUSPENDED, DEACTIVATED
    password_hash = Column(String, nullable=False)
    last_login_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    invitations = relationship("TeamInvitation", back_populates="invited_by", foreign_keys="TeamInvitation.invited_by_id")
    activity_logs = relationship("ActivityLog", back_populates="user")


class AdminSession(Base):
    __tablename__ = "admin_sessions"

    id = Column(Integer, primary_key=True, index=True)
    admin_id = Column(Integer, ForeignKey("admin_users.id"), nullable=False, index=True)
    token_hash = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    admin = relationship("AdminUser")


class TeamInvitation(Base):
    __tablename__ = "team_invitations"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, nullable=False, index=True)
    name = Column(String, default="")
    role = Column(String, nullable=False)  # ADMIN, SALES, SEO_ANALYST, SUPER_ADMIN
    token_hash = Column(String, unique=True, index=True, nullable=False)
    expires_at = Column(DateTime, nullable=False)
    used_at = Column(DateTime, nullable=True)
    invited_by_id = Column(Integer, ForeignKey("admin_users.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    invited_by = relationship("AdminUser", back_populates="invitations", foreign_keys=[invited_by_id])


class ActivityLog(Base):
    __tablename__ = "activity_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=True, index=True)
    user_email = Column(String, default="")
    user_name = Column(String, default="")
    user_role = Column(String, default="")
    action = Column(String, nullable=False, index=True)
    resource = Column(String, default="")
    details = Column(Text, default="")
    status = Column(String, default="SUCCESS")  # SUCCESS, FAILED, BLOCKED
    ip_address = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    user = relationship("AdminUser", back_populates="activity_logs")


class LeadNote(Base):
    __tablename__ = "lead_notes"

    id = Column(Integer, primary_key=True, index=True)
    lead_id = Column(Integer, ForeignKey("seo_leads.id"), nullable=False, index=True)
    user_id = Column(Integer, ForeignKey("admin_users.id"), nullable=True)
    author_name = Column(String, default="")
    author_email = Column(String, default="")
    note = Column(Text, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    lead = relationship("SEOLead", back_populates="notes")


class SEOLead(Base):
    __tablename__ = "seo_leads"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    company = Column(String, default="")
    email = Column(String, nullable=False)
    phone = Column(String, default="")
    website = Column(String, nullable=False)
    initial_score = Column(Float, nullable=True)
    message = Column(Text, default="")
    status = Column(String, default="NEW", nullable=False)  # NEW, CONTACTED, QUALIFIED, CONVERTED, CLOSED
    source = Column(String, default="public_checker", nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=True, index=True)
    timeline_json = Column(Text, default="[]", nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("Client")
    notes = relationship("LeadNote", back_populates="lead", cascade="all, delete-orphan", order_by="desc(LeadNote.created_at)")


class PublicScan(Base):
    __tablename__ = "public_scans"

    id = Column(Integer, primary_key=True, index=True)
    target_url = Column(String, nullable=False)
    score = Column(Float, nullable=True)
    ip_address = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)


class ScheduledAudit(Base):
    __tablename__ = "scheduled_audits"

    id = Column(Integer, primary_key=True, index=True)
    website_id = Column(Integer, ForeignKey("websites.id"), index=True, nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True, nullable=True)
    frequency = Column(String, default="WEEKLY", nullable=False)  # DAILY, WEEKLY, MONTHLY
    status = Column(String, default="ACTIVE", nullable=False)     # ACTIVE, PAUSED
    last_run_at = Column(DateTime, nullable=True)
    next_run_at = Column(DateTime, default=datetime.utcnow, nullable=False)
    max_pages = Column(Integer, default=50)
    created_at = Column(DateTime, default=datetime.utcnow)

    website = relationship("Website")
    client = relationship("Client")


class KeywordProject(Base):
    __tablename__ = "keyword_projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True, nullable=True)
    description = Column(String, default="")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("Client")
    keywords = relationship("SavedKeyword", back_populates="project", cascade="all, delete-orphan")


class SavedKeyword(Base):
    __tablename__ = "saved_keywords"

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("keyword_projects.id"), index=True, nullable=False)
    keyword = Column(String, nullable=False, index=True)
    search_volume = Column(Integer, nullable=True)
    cpc = Column(Float, nullable=True)
    keyword_difficulty = Column(Float, nullable=True)
    intent = Column(String, nullable=True)
    competition = Column(Float, nullable=True)
    cluster = Column(String, nullable=True)
    source = Column(String, default="research")
    created_at = Column(DateTime, default=datetime.utcnow)

    project = relationship("KeywordProject", back_populates="keywords")


class CompetitorComparison(Base):
    __tablename__ = "competitor_comparisons"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    target_domain = Column(String, nullable=False, index=True)
    competitor_domains = Column(String, default="[]")  # JSON serialized list of competitor domains
    client_id = Column(Integer, ForeignKey("clients.id"), index=True, nullable=True)
    market_country = Column(Integer, default=2840)
    market_language = Column(String, default="en")
    data_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("Client")


class BacklinkSnapshot(Base):
    __tablename__ = "backlink_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    target_domain = Column(String, nullable=False, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True, nullable=True)
    data_provider = Column(String, default="DataForSEO / OpenPageRank")
    total_backlinks = Column(Integer, default=0)
    referring_domains = Column(Integer, default=0)
    referring_main_domains = Column(Integer, default=0)
    referring_ips = Column(Integer, default=0)
    dofollow_backlinks = Column(Integer, default=0)
    nofollow_backlinks = Column(Integer, default=0)
    domain_authority = Column(Float, nullable=True)
    internal_equity_score = Column(Float, nullable=True)
    spam_score = Column(Float, nullable=True)
    data_json = Column(Text, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("Client")


class TrackedKeyword(Base):
    __tablename__ = "tracked_keywords"

    id = Column(Integer, primary_key=True, index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True, nullable=True)
    website_id = Column(Integer, ForeignKey("websites.id"), index=True, nullable=True)
    keyword = Column(String, nullable=False, index=True)
    target_domain = Column(String, nullable=False, index=True)
    location_code = Column(Integer, default=2840)  # Default 2840 (US)
    location_name = Column(String, default="United States")
    language_code = Column(String, default="en")
    device = Column(String, default="desktop")  # desktop or mobile
    competitor_domains = Column(String, default="[]")  # JSON list of competitor domains
    check_frequency = Column(String, default="daily")  # daily, weekly, manual
    tags = Column(String, default="")  # Comma-separated tags
    current_position = Column(Integer, nullable=True)
    previous_position = Column(Integer, nullable=True)
    best_position = Column(Integer, nullable=True)
    position_change = Column(Integer, default=0)
    latest_url = Column(String, default="")
    search_volume = Column(Integer, nullable=True)
    cpc = Column(Float, nullable=True)
    keyword_difficulty = Column(Float, nullable=True)
    last_checked_at = Column(DateTime, nullable=True)
    is_active = Column(Integer, default=1)
    alert_enabled = Column(Integer, default=1)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("Client")
    website = relationship("Website")
    observations = relationship("RankingObservation", back_populates="tracked_keyword", cascade="all, delete-orphan")
    alerts = relationship("RankingAlert", back_populates="tracked_keyword", cascade="all, delete-orphan")


class RankingObservation(Base):
    __tablename__ = "ranking_observations"

    id = Column(Integer, primary_key=True, index=True)
    tracked_keyword_id = Column(Integer, ForeignKey("tracked_keywords.id", ondelete="CASCADE"), index=True, nullable=False)
    collected_at = Column(DateTime, default=datetime.utcnow, index=True)
    target_domain = Column(String, nullable=False, index=True)
    device = Column(String, default="desktop")
    position = Column(Integer, nullable=True)
    absolute_position = Column(Integer, nullable=True)
    ranked_url = Column(String, default="")
    serp_features_json = Column(Text, default="[]")
    competitor_positions_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)

    tracked_keyword = relationship("TrackedKeyword", back_populates="observations")


class RankingAlert(Base):
    __tablename__ = "ranking_alerts"

    id = Column(Integer, primary_key=True, index=True)
    tracked_keyword_id = Column(Integer, ForeignKey("tracked_keywords.id", ondelete="CASCADE"), index=True, nullable=False)
    target_domain = Column(String, nullable=False, index=True)
    keyword = Column(String, nullable=False)
    alert_type = Column(String, nullable=False)
    severity = Column(String, default="INFO")
    message = Column(Text, nullable=False)
    previous_position = Column(Integer, nullable=True)
    new_position = Column(Integer, nullable=True)
    is_read = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    tracked_keyword = relationship("TrackedKeyword", back_populates="alerts")


class AgencyBranding(Base):
    __tablename__ = "agency_branding"

    id = Column(Integer, primary_key=True, index=True)
    agency_name = Column(String, default="Aviance SEO Agency")
    tagline = Column(String, default="Enterprise Search Engine Optimization & Telemetry")
    logo_url = Column(String, default="")
    primary_color = Column(String, default="#4F46E5")
    secondary_color = Column(String, default="#0F172A")
    website = Column(String, default="https://aviance.ai")
    support_email = Column(String, default="reports@aviance.ai")
    phone = Column(String, default="+1 (800) 555-0199")
    footer_text = Column(String, default="Confidential & Proprietary Client Intelligence Report")
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Project(Base):
    __tablename__ = "projects"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    description = Column(String, default="")
    client_id = Column(Integer, ForeignKey("clients.id"), index=True, nullable=True)
    status = Column(String, default="ACTIVE", index=True)  # ACTIVE, ARCHIVED
    target_domains_json = Column(Text, default="[]")
    settings_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("Client")
    websites = relationship("Website", back_populates="project")


class PageFinding(Base):
    __tablename__ = "page_findings"

    id = Column(Integer, primary_key=True, index=True)
    audit_id = Column(Integer, ForeignKey("audits.id", ondelete="CASCADE"), index=True, nullable=False)
    url = Column(String, nullable=False, index=True)
    check_id = Column(String, nullable=False, index=True)
    category = Column(String, nullable=False, index=True)
    severity = Column(String, nullable=False, index=True)  # critical, high, medium, low
    problem_description = Column(String, nullable=False)
    suggested_correction = Column(String, default="")
    evidence_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    audit = relationship("Audit", back_populates="page_findings")


class ReportExport(Base):
    __tablename__ = "report_exports"

    id = Column(Integer, primary_key=True, index=True)
    audit_id = Column(Integer, ForeignKey("audits.id"), index=True, nullable=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True, nullable=True)
    website_id = Column(Integer, ForeignKey("websites.id"), index=True, nullable=True)
    report_type = Column(String, nullable=False, index=True)  # EXECUTIVE, TECHNICAL, etc.
    format = Column(String, nullable=False, index=True)       # PDF, CSV, EXCEL, JSON
    filename = Column(String, nullable=False)
    file_path = Column(String, default="")
    file_size_bytes = Column(Integer, default=0)
    download_count = Column(Integer, default=0)
    provenance_json = Column(Text, default="{}")
    created_at = Column(DateTime, default=datetime.utcnow, index=True)

    audit = relationship("Audit")
    client = relationship("Client")
    website = relationship("Website")


class BackgroundJob(Base):
    __tablename__ = "background_jobs"

    id = Column(String, primary_key=True, index=True)  # UUID token string
    job_type = Column(String, nullable=False, index=True)  # AUDIT, RANK_TRACK, BACKLINK_SYNC, REPORT_EXPORT
    target_url = Column(String, default="", index=True)
    client_id = Column(Integer, ForeignKey("clients.id"), index=True, nullable=True)
    website_id = Column(Integer, ForeignKey("websites.id"), index=True, nullable=True)
    audit_id = Column(Integer, ForeignKey("audits.id"), index=True, nullable=True)
    status = Column(String, nullable=False, default="QUEUED", index=True)  # QUEUED, RUNNING, COMPLETED, FAILED, CANCELLED
    progress_pct = Column(Float, default=0.0)
    progress_phase = Column(String, default="queued")
    progress_json = Column(Text, default="{}")
    retry_count = Column(Integer, default=0)
    max_retries = Column(Integer, default=3)
    error_message = Column(String, default="")
    started_at = Column(DateTime, nullable=True)
    completed_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow, index=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    client = relationship("Client")
    website = relationship("Website")
    audit = relationship("Audit")


def init_db():
    if IS_MONGO:
        try:
            db = get_mongo_db()
            logger.info(f"Connected to MongoDB Atlas: {db.name}")

            # Ensure essential indexes
            try:
                db["admin_users"].create_index("email", unique=True)
                db["admin_sessions"].create_index("token_hash", unique=True)
                db["admin_sessions"].create_index("expires_at")
                db["team_invitations"].create_index("token_hash", unique=True)
                db["clients"].create_index("id", unique=True)
                db["websites"].create_index("id", unique=True)
                db["websites"].create_index("client_id")
                db["websites"].create_index("project_id")
                db["projects"].create_index("id", unique=True)
                db["projects"].create_index("client_id")
                db["audits"].create_index("id", unique=True)
                db["audits"].create_index([("created_at", -1)])
                db["audits"].create_index("job_id")
                db["audits"].create_index("client_id")
                db["audits"].create_index("website_id")
                db["audits"].create_index("project_id")
                db["public_reports"].create_index("id", unique=True)
                db["public_reports"].create_index("token", unique=True)
                db["seo_leads"].create_index("id", unique=True)
                db["seo_leads"].create_index("email")
                db["lead_notes"].create_index("id", unique=True)
                db["lead_notes"].create_index("lead_id")
                db["activity_logs"].create_index("id", unique=True)
                db["activity_logs"].create_index("created_at")
                db["public_scans"].create_index("id", unique=True)
                db["scheduled_audits"].create_index("id", unique=True)
                db["keyword_projects"].create_index("id", unique=True)
                db["saved_keywords"].create_index("id", unique=True)
                db["saved_keywords"].create_index("project_id")
                db["saved_keywords"].create_index("keyword")
                db["competitor_comparisons"].create_index("id", unique=True)
                db["competitor_comparisons"].create_index("target_domain")
                db["backlink_snapshots"].create_index("id", unique=True)
                db["backlink_snapshots"].create_index("target_domain")
                db["tracked_keywords"].create_index("id", unique=True)
                db["tracked_keywords"].create_index("target_domain")
                db["tracked_keywords"].create_index("keyword")
                db["ranking_observations"].create_index("tracked_keyword_id")
                db["ranking_alerts"].create_index("tracked_keyword_id")
                db["page_findings"].create_index("audit_id")
                db["page_findings"].create_index("url")
                db["report_exports"].create_index("id", unique=True)
                db["report_exports"].create_index("audit_id")
                db["background_jobs"].create_index("id", unique=True)
                db["background_jobs"].create_index("status")
            except Exception as e:
                logger.warning(f"Error ensuring MongoDB indexes: {e}")

            # Ensure _counters collection is initialized
            tables = [
                "admin_users", "clients", "websites", "audits", "public_reports",
                "team_invitations", "admin_sessions", "activity_logs", "lead_notes",
                "seo_leads", "public_scans", "scheduled_audits", "keyword_projects",
                "saved_keywords", "competitor_comparisons", "backlink_snapshots",
                "tracked_keywords", "ranking_observations", "ranking_alerts",
                "agency_branding", "projects", "page_findings", "report_exports",
                "background_jobs"
            ]
            for t in tables:
                try:
                    cur = db[t].find({}, {"id": 1}).sort("id", -1).limit(1)
                    doc = next(cur, None)
                    max_id = doc.get("id", 0) if doc else 0
                    db["_counters"].update_one({"_id": t}, {"$max": {"seq": max_id}}, upsert=True)
                except Exception as ce:
                    logger.warning(f"Error initializing counter for {t}: {ce}")
        except Exception as e:
            logger.error(f"MongoDB Atlas initialization warning: {e}")
        return

    # SQL mode initialization
    from sqlalchemy import inspect, text
    Base.metadata.create_all(bind=engine)
    if "sqlite" not in DB_PATH:
        return

    additions = {
        "clients": {"status": "VARCHAR NOT NULL DEFAULT 'ACTIVE'"},
        "audits": {
            "website_id": "INTEGER",
            "project_id": "INTEGER",
            "job_id": "VARCHAR",
            "status": "VARCHAR NOT NULL DEFAULT 'COMPLETED'",
            "progress_json": "TEXT NOT NULL DEFAULT '{}'",
            "provenance_json": "TEXT NOT NULL DEFAULT '{}'",
            "completed_at": "DATETIME",
        },
        "public_reports": {
            "client_id": "INTEGER",
            "website_id": "INTEGER",
            "snapshot_json": "TEXT NOT NULL DEFAULT '{}'",
            "published_at": "DATETIME",
            "disabled_at": "DATETIME",
        },
        "admin_users": {
            "name": "VARCHAR DEFAULT ''",
            "role": "VARCHAR NOT NULL DEFAULT 'SUPER_ADMIN'",
            "status": "VARCHAR NOT NULL DEFAULT 'ACTIVE'",
            "last_login_at": "DATETIME",
            "updated_at": "DATETIME",
        },
        "websites": {
            "project_id": "INTEGER",
            "gsc_property": "VARCHAR DEFAULT ''",
            "ga4_property_id": "VARCHAR DEFAULT ''",
            "connection_status_json": "TEXT NOT NULL DEFAULT '{}'",
        },
    }
    with engine.begin() as connection:
        inspector = inspect(connection)
        for table_name, columns in additions.items():
            existing = {column["name"] for column in inspector.get_columns(table_name)}
            for column_name, definition in columns.items():
                if column_name not in existing:
                    connection.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"))

        connection.execute(text("UPDATE admin_users SET role = 'SUPER_ADMIN' WHERE role IS NULL OR role = ''"))
        connection.execute(text("UPDATE admin_users SET status = 'ACTIVE' WHERE status IS NULL OR status = ''"))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
