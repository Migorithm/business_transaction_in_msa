# Business Transaction Service In MSA

<p>
Although some may disagree, I personally find it is quite difficult to find<br> 
good example MSA-based code in Python. For that reason, I decided to start this project<br>
to organize the 'doable' approaches to implementing DDD and EDA in Python.<br>
Example Project will be online business transaction.<br>
</p>



## Domain Models
Domain here refers to areas where business problems reside and Models refers to the methodology by which<br>
The domain problem can be solved. Therefore, models contain not only the business components(attributes)<br>
but also its behaviours(methods).<br><br>

As domains are at heart of domain-driven design whereby pretty much every state modifying action is driven,<br>
It should not have dependencies on anything else but Plain Old Python Object(a.k.a POPO).<br>
So here, in order not to have our models depend on infrastructure concerns, dependency inversion was adopted.<br>
That is, it is not aware of SQLAlchemy, for example. Rather, Infrastructure layer(orm) is aware of its model.<br>
But then again, to streamline the query process, property decorator was replaced at runtime when mapping is made as follows.<br>

```python
#/app/adapters/delivery_orm.py & service_orm.py
import inspect
from sqlalchemy.ext.hybrid import hybrid_property
from app.domain import base

def extract_models(module):
    for _, class_ in inspect.getmembers(module, lambda o: isinstance(o, type)):
        if issubclass(class_, base.Base) and class_ != base.Base:
            yield class_
        if issubclass(class_, base.PointBase) and class_ != base.PointBase:
            yield class_

def _get_set_hybrid_properties(models):
    for model in models:
        for method_name, _ in inspect.getmembers(model, lambda o: isinstance(o, property)):
            attr = getattr(model, method_name)
            get_ = hybrid_property(attr.fget)
            set_ = get_.setter(attr.fset) if attr.fset else None
            setattr(model, method_name, get_)
            if set_:
                setattr(model, method_name, set_)

def start_mappers():
    _get_set_hybrid_properties(extract_models(service))
    ...
```

### Delivery Transaction And Service Transaction
Here in this transaction service, there are two different kinds of transactions.<br>
The first is for items(skus) that is subject to delivery(shipping) and<br>
the other is for items that is NOT subject to delivery such as e-voucher.<br>
Because of its obvious simiarity, you may think that why not just have<br>
optional 'delivery info' rather than having two different transaction context.<br><br>

As valid as that may sound, it is problemmatic as 'optional' mapping to a database entity<br>
means that you cannot select things for update, leading to not being able to set<br>
consistent boundary.<br> 

## Persistent Layer(infrastructure layer)

### Optimistic concurrency control
I implemented optimistic concurrency control just allow for fast read at a time reliable write is secured<br>
by introducing version column as follows.<br>

```python
#/app/domain/delivery
@dataclass(eq=False)
class DeliveryTransaction(Order):
    xmin: int = field(init=False, repr=False)


#/app/adapters/delivery_orm
from sqlalchemy import (
    ...
    FetchedValue)
delivery_transactions = Table(
    Column("xmin", Integer, system=True, server_default=FetchedValue()),  # system column
)

def start_mapper():
    mapper_registry.map_imperatively(
            delivery.DeliveryTransaction,
            delivery_transactions,
            ...
            ... 
            version_id_col=delivery_transactions.c.xmin,
            version_id_generator=False,
        )
```
FetchedValue is used when the database is configured to provide some automatic default for a column.<br>
Here, I used this to get serverside values to manage update version.<br>
Note that I used Postgres for this implementation and you may or may not be required to take different way<br>
to achieve the same goal.<br>

### SQLAlchemy 2.0 syntax + async DB API
To best use FastAPI framework, simply using 'async def' is not enough as the most of the bottle neck<br>
points are at I/O bound calls. So, I used asyncpg aligned with SQLAlalchemy 2.0 syntax for<br>
asynchronous operations. <br>

```python
#/app/db.py
if STAGE not in ("testing", "ci-testing"):
    engine = create_async_engine(
        PERSISTENT_DB.get_uri(), pool_pre_ping=True, pool_size=10, max_overflow=20, future=True
    )
    async_transactional_session_factory = sessionmaker(
        engine, expire_on_commit=False, autoflush=False, class_=AsyncSession
    )
    autocommit_engine = engine.execution_options(isolation_level="AUTOCOMMIT")
```

### Duplexing of engines to prevent idle in transasction
It's best to have transaction time as short as possible because otherwise you may hold the transaction.<br>
longer than rolling-in traffics, leading to idle in transaction. <br>
As you can imagine, most of requests are 'GET' request and that call shouldn't change DB entity. <br>
For that reason, I created two different engines, one for transactional and the other for read-only. <br>

```python
#/app/db.py
engine: AsyncEngine | None = None #transactional engine
autocommit_engine: AsyncEngine | None = None #read-only engine
async_transactional_session_factory: sessionmaker | None = None
async_autocommit_session_factory: sessionmaker | None = None

if STAGE not in ("testing", "ci-testing"):
    engine = create_async_engine(
        PERSISTENT_DB.get_uri(), pool_pre_ping=True, pool_size=10, max_overflow=20, future=True
    )
    async_transactional_session_factory = sessionmaker(
        engine, expire_on_commit=False, autoflush=False, class_=AsyncSession
    )
    autocommit_engine = engine.execution_options(isolation_level="AUTOCOMMIT")
    async_autocommit_session_factory = sessionmaker(autocommit_engine, expire_on_commit=False, class_=AsyncSession)
```

### Event listeners to have temporary db objects mananged in application
'temporary db objects' are referred to not persistent entity but rather db objects that are<br>
dependent on persistent entity therefore removable such as<br>
- Trigger
- Trigger Functions
- Custom Functions
- Views
In 'app.adapters.event_listeners', you will see trigger, function, view generating function<br>
and registering logics as follows.<br>
```python
#/app/adapters/event_listeners.py
from sqlalchemy.schema import DDL

def register_ddls(func):
    @wraps(func)
    def wrapped(*args, **kwargs):
        create_ddl, drop_ddl = func(*args, **kwargs)
        create_ddl.name = kwargs["name"]
        registered_ddls.setdefault(kwargs["object_type"], []).append((create_ddl, drop_ddl))

    return wrapped


@register_ddls
def generate_ddl(
    *,
    object_type: str,
    name: str,
    stmt: str,
    trigger_when: TRIGGER_WHEN | None = None,
    trigger_option: Sequence[TRIGGER_OPTION] | TRIGGER_OPTION | None = None,
    trigger_of: Sequence[str] | str | None = None,
    trigger_on: str | None = None,
    **kwargs,
) -> tuple[DDL, DDL]:
    create_format: Callable | None = None
    drop_format: Callable | None = None
    match object_type.upper():
        case "VIEW":
            create_format = "CREATE OR REPLACE {} {} AS {}".format
            drop_format = "DROP {} IF EXISTS {}".format
        case "PROCEDURE" | "FUNCTION":
            temp_format = "CREATE OR REPLACE {} {}(%s) {}" % (",".join([f"{k} {v}" for k, v, in kwargs.items()]))
            create_format = temp_format.format
            drop_format = "DROP {} IF EXISTS {} CASCADE".format
        case "TRIGGER":
            if not all((trigger_option, trigger_when, trigger_on)):
                raise Exception
            assert trigger_option

            temp_format = "CREATE OR REPLACE {} {} %s %s" % (
                trigger_when,
                " OR ".join(trigger_option if not isinstance(trigger_option, str) else [trigger_option]),
            )
            if trigger_of:
                temp_format += " OF %s " % ",".join(trigger_of if not isinstance(trigger_of, str) else [trigger_of])
            temp_format += f" ON {trigger_on}"
            temp_format += "{}"
            create_format = temp_format.format

            drop_temp_format = "DROP {} IF EXISTS {} ON %s CASCADE;" % (trigger_on)
            drop_format = drop_temp_format.format
        case _:
            raise Exception

    create_view_ddl = DDL(create_format(object_type.upper(), name, stmt)).execute_if(dialect=("postgresql", "sqlite"))
    drop_view_ddl = DDL(drop_format(object_type.upper(), name)).execute_if(dialect="postgresql")
    return create_view_ddl, drop_view_ddl
```
### Event Store Being A RDBMS
Ideal event store should meet the following requirement:
- 'full-sequential-read' of the events in our event store.
- Reading all events for a given entity(aggregate)
- Before we accept a change to an entity, we need to persist that change, meaning the addition of event to event store.
- A desired change may not be only a single event but multiple. So we need an event store that can process multiple events emission.
- Event sourcing-based applications produce a lot of data. Therefore the event store must be scalable in terms of data

Leaving the requirements aside, event sourcing is to keep track of what an aggregate reaches at a certain point.<br>
It is particularly the case for monetary transactions. So complexity in that case is justified anyway.<br>
The problem is, when a company like startup literally starts their business, the traffic is uncertain.<br>
So implementing such a demanding job with multiple different storage can be overwhelming.<br>
For those reasons, I decided to use Postgres as event store. 

```python
#/app/adapters/eventstore
event_store = Table(
    "cvm_transaction_event_store",
    mapper_registry.metadata,
    Column("global_seq", Integer, global_seq, server_default=global_seq.next_value(), primary_key=True),
    Column("create_dt", postgresql.TIMESTAMP(timezone=True), default=func.now(), server_default=func.now()),
    Column("aggregate_id", String, nullable=False),
    Column("aggregate_version", Integer, nullable=False, unique=True),
    Column("aggregate_type", String, nullable=False),
    Column("payload", postgresql.JSONB, nullable=False),
)

idx_on_event_store = Index("idx_on_event_store", event_store.c.aggregate_id, event_store.c.aggregate_version)
```
Note that multicolumn index were implemented for better search.

## Test 
### Conftest
Asynchrounous operation in pytest requires its own event loop. For that reason, the following<br>
code lines were implemented.<br>
```python
@pytest.fixture(scope="session")
def event_loop():
    """
    Creates an instance of the default event loop for the test session
    """
    loop = asyncio.get_event_loop_policy().new_event_loop()
    if sys.platform.startswith("win") and sys.version_info[:2] >= (3, 8):
        # Avoid "RuntimeError: Event loop is closed" on Windows when tearing down tests
        # https://github.com/encode/httpx/issues/914
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    yield loop
    loop.close()
```

Plus, the following SQL statement is to drop temporary db objects such as views, triggers,
custom functions and trigger functions. 
```python
create_drop_procedure = """
CREATE OR REPLACE PROCEDURE drop_all_db_objects()
AS $$
    DECLARE v_rec record;
            v_schema_obj text;
            f_rec record;
            f_schema_obj text;
            tr_rec record;
            tr_schema_obj text;
    BEGIN
        FOR v_rec in (SELECT table_name FROM information_schema.views where table_schema = 'public') LOOP
            v_schema_obj := concat('public.',v_rec.table_name);
            EXECUTE format(
                'DROP VIEW IF EXISTS %s;', v_schema_obj
            );
        END LOOP;

        FOR tr_rec in (
            SELECT trigger_name,event_object_table
            FROM information_schema.triggers as tri where tri.trigger_schema ='public'
            ) LOOP
            tr_schema_obj := (tr_rec.trigger_name || ' ON ' ||  tr_rec.event_object_table );
            EXECUTE format(
                'DROP TRIGGER IF EXISTS %s CASCADE;', tr_schema_obj
            );
        END LOOP;

        FOR f_rec in (
            SELECT routine_name
            FROM information_schema.routines
            WHERE routine_schema='public' and routine_type='FUNCTION' and routine_name like 'trx_%'
            ) LOOP
            f_schema_obj := concat('public.',f_rec.routine_name);
            EXECUTE format(
                'DROP FUNCTION IF EXISTS %s CASCADE;', f_schema_obj
            );
        END LOOP;

END;

$$ language plpgsql;
"""
```

Along with the above sql statement, I implement DDL generating logic as in the following:<br>
```python
#app/tests/conftest.py
from app.adapters.event_listeners import registered_ddls 
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine
@pytest_asyncio.fixture(scope="session")
async def aio_pg_engine():
    engine = create_async_engine(
        PERSISTENT_DB.get_test_uri(),
        future=True,  # poolclass=NullPool
    )
    async with engine.begin() as conn:
        drop_stmt = f"DROP TABLE IF EXISTS {','.join(delivery_metadata.tables.keys())},\
            {','.join(service_metadata.tables.keys())} CASCADE;"
        await conn.execute(text(drop_stmt))

        await conn.execute(text(create_drop_procedure)) #here
        await conn.execute(
            text(
                """
        call drop_all_db_objects();
        """
            )
        )
        for _, list_ in registered_ddls.items():
            for c_ddl, _ in list_:
                event.listen(delivery_metadata, "after_create", c_ddl)
                # await conn.execute(text(c_ddl.statement.replace(r"%%",r"%")))

        await conn.run_sync(delivery_metadata.create_all)
        await conn.run_sync(service_metadata.create_all)

    delivery_start_mappers()
    service_start_mappers()

    yield engine

    clear_mappers()
    # engine.sync_engine.dispose()

```
