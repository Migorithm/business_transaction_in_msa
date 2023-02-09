from __future__ import annotations

from abc import ABC, abstractmethod
from asyncio import iscoroutinefunction
from collections import OrderedDict
from functools import wraps
from typing import Generic, Literal, Type, TypeVar

from sqlalchemy import and_, func, or_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.future import select
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import joinedload, selectinload
from sqlalchemy.orm.strategy_options import Load
from sqlalchemy.sql.elements import BinaryExpression
from sqlalchemy.sql.selectable import Select

# from app.domain import delivery as do_models
# from app.domain import service as so_models
from app.domain.base import event_generator

ModelType = TypeVar("ModelType", bound=object)
LOGICAL_OPERATOR = Literal["and", "or"]


class Exceptions:
    class InvalidConditionGiven(Exception):
        ...

    class InvalidOperation(Exception):
        ...

    class InvalidRelationshipGiven(Exception):
        ...


class RepositoryDecorators:
    @staticmethod
    def query_resetter(func):
        @wraps(func)
        async def async_wrapper(self: AsyncSqlAlchemyRepository | AsyncSqlAlchemyViewRepository, *args, **kwargs):
            res = await func(self, *args, **kwargs)
            self._query_reset()
            return res

        @wraps(func)
        def sync_wrapper(self: AsyncSqlAlchemyRepository | AsyncSqlAlchemyViewRepository, *args, **kwargs):
            res = func(self, *args, **kwargs)
            self._query_reset()
            return res

        if iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper

    @staticmethod
    def event_gatherer(func):
        @wraps(func)
        async def async_wrapper(self: AsyncSqlAlchemyRepository, *args, **kwargs):
            res = await func(self, *args, **kwargs)
            if res and self.event_collectable:
                self._add_up_events(model=res)
            return res

        @wraps(func)
        def sync_wrapper(self: AsyncSqlAlchemyRepository, *args, **kwargs):
            res = func(self, *args, **kwargs)
            if self.event_collectable:
                self._add_up_events(model=res)
            return res

        if iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper


class AbstractRepository(ABC):
    def add(self, model):
        self._add(model)

    def add_all(self, models):
        self._add_all(models)

    @RepositoryDecorators.query_resetter
    async def get(self, is_update=False):
        return await self._get(is_update=is_update)

    @RepositoryDecorators.query_resetter
    async def list(self, scalar=True, is_update=False):
        return await self._list(scalar=scalar, is_update=is_update)

    def filter(self, *args, logical_operator: LOGICAL_OPERATOR = "and", **kwargs):
        self._filter(*args, logical_operator=logical_operator, **kwargs)
        return self

    @abstractmethod
    def _add(self, model):
        raise NotImplementedError

    @abstractmethod
    def _add_all(self, models):
        raise NotImplementedError

    @abstractmethod
    async def _get(self, *, is_update):
        raise NotImplementedError

    @abstractmethod
    async def _list(self, *, scalar, is_update):
        raise NotImplementedError

    @abstractmethod
    def _filter(self, *args, logical_operator: LOGICAL_OPERATOR, **kwargs):
        raise NotImplementedError

    @abstractmethod
    def _query_reset(self):
        raise NotImplementedError


class SqlAlchemyRepository(AbstractRepository):
    def __init__(self, *, model: Type[ModelType], session: AsyncSession):
        self.model = model
        self._base_query: Select = select(self.model)
        self.session = session
        self.relationship_metadata = inspect(self.model).relationships.items()
        self.tablename_collection_relationship_mapper: dict[str, tuple[str, bool]] = {
            str(v.target.name): (str(v), v.uselist) for _, v in self.relationship_metadata
        }

    def _query_reset(self):
        self._base_query = select(self.model)

    def filter(self, *args, logical_operator: LOGICAL_OPERATOR = "and", **kwargs):
        self._filter(*args, logical_operator=logical_operator, **kwargs)
        return self

    def _filter(self, *args, logical_operator: LOGICAL_OPERATOR, **kwargs):
        """
        colname__operator = value
        """
        cond: list[BinaryExpression] = []

        for arg in args:
            if isinstance(arg, BinaryExpression):
                self._base_query = self._base_query.filter(arg)

            else:
                raise Exceptions.InvalidConditionGiven(f"Non-keywords argument must be BinaryExpression : {str(arg)}")

        for key, val in kwargs.items():
            match key.split("__", 1):
                case [col_name, op]:
                    try:
                        col = getattr(self.model, col_name)
                    except AttributeError:
                        raise Exceptions.InvalidConditionGiven(
                            f"No Such Column({col_name}) Exist For This Model: {str(self.model)}"
                        )
                    else:
                        self._collect_condition(cond=cond, col=col, op=op, val=val)

                case _:
                    raise Exceptions.InvalidConditionGiven(
                        "Filter Option Not Correctly Given. (Hint) Use The Following Format - colname__eq = value"
                    )
        if logical_operator == "and":
            self._base_query = self._base_query.where(and_(True, *cond))
        else:
            self._base_query = self._base_query.where(or_(*cond))

    @classmethod
    def _collect_condition(cls, *, cond, col, op: str, val: str):
        """
        Condition Filter Collect
        Sytax :
            - model_attribute__eq = value
            - model_attribute__not_eq = value
            - model_attribute__gt = value
            - model_attribute_lt = value
            - child_collection__any_child_attribute__in = value
            - child_collection__any_child_attribute__eq = value

        """
        if op == "eq":
            cond.append((col == val))
        elif op == "not_eq":
            cond.append((col != val))
        elif op == "gt":
            cond.append((col > val))
        elif op == "gte":
            cond.append((col >= val))
        elif op == "lt":
            cond.append((col < val))
        elif op == "lte":
            cond.append((col <= val))
        elif op == "in":
            cond.append((col.in_(val)))
        elif op == "not_in":
            cond.append((col.not_in(val)))
        elif op == "btw":
            cond.append((col.between(*val)))
        elif op == "like":
            cond.append((col.like(val + "%")))
        elif op == "range":
            sub_cond = []
            for var in val:
                sub_cond.append((col.between(*var)))
            cond.append(or_(*sub_cond))
        elif op.startswith("any") or op.startswith("has"):
            sub_model = col.mapper.class_
            sub_col_name, sub_op = op[4:].split("__")
            sub_col = getattr(sub_model, sub_col_name)
            cls._collect_condition(cond=cond, col=sub_col, op=sub_op, val=val)
            sub_col_condition = cond.pop()
            cond.append(col.any(sub_col_condition)) if op.startswith("any") else cond.append(col.has(sub_col_condition))
        else:
            raise Exceptions.InvalidConditionGiven(f"No Such Operation Exist: {op}")

    def load_relationships(self, *args, reset=False):
        if reset:
            self._base_query = select(self.model)
        relationship_metadata = self.relationship_metadata
        tablename_collection_relationship_mapper = self.tablename_collection_relationship_mapper

        origin = self.model
        _load_options: Load | None = None

        for class_ in args:
            tb_name = str(class_._sa_class_manager.mapper.persist_selectable.name)
            if tb_name in tablename_collection_relationship_mapper:
                is_one_to_many = tablename_collection_relationship_mapper[tb_name][1]
                collection_name = getattr(origin, tablename_collection_relationship_mapper[tb_name][0].split(".")[1])
                if is_one_to_many:
                    _load_options = (
                        selectinload(collection_name)
                        if _load_options is None
                        else _load_options.selectinload(collection_name)
                    )
                else:
                    _load_options = (
                        joinedload(collection_name)
                        if _load_options is None
                        else _load_options.joinedload(collection_name)
                    )
            else:
                raise Exceptions.InvalidRelationshipGiven
            relationship_metadata = inspect(class_).relationships.items()
            tablename_collection_relationship_mapper = {
                str(v.target.name): (str(v), v.uselist) for _, v in relationship_metadata
            }
            origin = class_

        self._base_query = self._base_query.options(_load_options)

    # def load_aggregate(self):
    #     match self.model:
    #         case do_models.DeliveryTransaction:
    #             self._base_query = (
    #                 self._base_query.options(
    #                     selectinload(do_models.DeliveryTransaction.delivery_orders)
    #                     .selectinload(do_models.DeliveryOrder.delivery_skus)
    #                     .selectinload(do_models.DeliverySku.delivery_sku_logs)
    #                     .joinedload(do_models.DeliverySkuLog.delivery_sku)
    #                     .joinedload(do_models.DeliverySku.delivery_product)
    #                     .joinedload(do_models.DeliveryProduct.delivery_group)
    #                     .selectinload(do_models.DeliveryGroup.delivery_products)
    #                     .selectinload(do_models.DeliveryProduct.delivery_skus)
    #                 )
    #                 .options(
    #                     selectinload(do_models.DeliveryTransaction.delivery_payment).selectinload(
    #                         do_models.DeliveryPayment.delivery_point_units
    #                     )
    #                 )
    #                 .options(
    #                     selectinload(do_models.DeliveryTransaction.delivery_payment).selectinload(
    #                         do_models.DeliveryPayment.delivery_payment_refunds
    #                     )
    #                 )
    #                 .options(selectinload(do_models.DeliveryTransaction.delivery_payment_logs))
    #                 .options(
    #                     selectinload(do_models.DeliveryTransaction.delivery_payment)
    #                     .selectinload(do_models.DeliveryPayment.delivery_transaction)
    #                     .selectinload(do_models.DeliveryTransaction.delivery_orders)
    #                     .selectinload(do_models.DeliveryOrder.delivery_skus)
    #                     .joinedload(do_models.DeliverySku.delivery_product)
    #                 )
    #             )

    #         case do_models.DeliveryOrder:
    #             self._base_query = (
    #                 self._base_query.options(
    #                     selectinload(do_models.DeliveryOrder.delivery_skus)
    #                     .joinedload(do_models.DeliverySku.delivery_product)
    #                     .joinedload(do_models.DeliveryProduct.delivery_group)
    #                     .selectinload(do_models.DeliveryGroup.delivery_products)
    #                     .selectinload(do_models.DeliveryProduct.delivery_skus)
    #                 )
    #                 .options(selectinload(do_models.DeliveryOrder.delivery_products))
    #                 .options(
    #                     joinedload(do_models.DeliveryOrder.delivery_transaction).selectinload(
    #                         do_models.DeliveryTransaction.delivery_orders
    #                     )
    #                 )
    #                 .options(
    #                     joinedload(do_models.DeliveryOrder.delivery_transaction)
    #                     .selectinload(do_models.DeliveryTransaction.delivery_payment)
    #                     .selectinload(do_models.DeliveryPayment.delivery_point_units)
    #                 )
    #                 .options(
    #                     joinedload(do_models.DeliveryOrder.delivery_transaction)
    #                     .selectinload(do_models.DeliveryTransaction.delivery_payment)
    #                     .selectinload(do_models.DeliveryPayment.delivery_payment_refunds)
    #                 )
    #             )
    #         case do_models.DeliverySku:
    #             self._base_query = self._base_query.options(
    #                 joinedload(do_models.DeliverySku.delivery_order).selectinload(do_models.DeliveryOrder.delivery_skus)
    #             ).options(
    #                 joinedload(do_models.DeliverySku.delivery_product)
    #                 .joinedload(do_models.DeliveryProduct.delivery_group)
    #                 .selectinload(do_models.DeliveryGroup.delivery_products)
    #                 .selectinload(do_models.DeliveryProduct.delivery_skus)
    #             )
    #         case so_models.ServiceTransaction:
    #             self._base_query = (
    #                 self._base_query.options(
    #                     selectinload(so_models.ServiceTransaction.service_orders)
    #                     .selectinload(so_models.ServiceOrder.service_skus)
    #                     .selectinload(so_models.ServiceSku.service_sku_logs)
    #                     .joinedload(so_models.ServiceSkuLog.service_sku)
    #                     .joinedload(so_models.ServiceSku.service_order)
    #                 )
    #                 .options(
    #                     selectinload(so_models.ServiceTransaction.service_payment).selectinload(
    #                         so_models.ServicePayment.service_payment_refunds
    #                     )
    #                 )
    #                 .options(
    #                     selectinload(so_models.ServiceTransaction.service_payment).selectinload(
    #                         so_models.ServicePayment.service_point_units
    #                     )
    #                 )
    #                 .options(selectinload(so_models.ServiceTransaction.service_payment_logs))
    #                 .options(
    #                     selectinload(so_models.ServiceTransaction.service_payment)
    #                     .selectinload(so_models.ServicePayment.service_transaction)
    #                     .selectinload(so_models.ServiceTransaction.service_orders)
    #                     .selectinload(so_models.ServiceOrder.service_skus)
    #                 )
    #             )
    #         case so_models.ServiceOrder:
    #             self._base_query = (
    #                 self._base_query.options(
    #                     selectinload(so_models.ServiceOrder.service_skus)
    #                     .joinedload(so_models.ServiceSku.service_order)
    #                     .joinedload(so_models.ServiceOrder.service_transaction)
    #                     .selectinload(so_models.ServiceTransaction.service_payment)
    #                     .selectinload(so_models.ServicePayment.service_point_units)
    #                 )
    #                 .options(
    #                     joinedload(so_models.ServiceOrder.service_transaction)
    #                     .selectinload(so_models.ServiceTransaction.service_payment)
    #                     .selectinload(so_models.ServicePayment.service_payment_refunds)
    #                 )
    #                 .options(
    #                     joinedload(so_models.ServiceOrder.service_transaction).selectinload(
    #                         so_models.ServiceTransaction.service_payment_logs
    #                     )
    #                 )
    #             )


class AsyncSqlAlchemyRepository(Generic[ModelType], SqlAlchemyRepository):
    def __init__(self, *, model: Type[ModelType], session: AsyncSession, event_collectable=True):
        super().__init__(model=model, session=session)
        self.event_collectable = event_collectable
        self.events: OrderedDict = OrderedDict()
        # self.load_aggregate()

    def raise_event(self, event_type: str, **kwargs):
        self.events[event_generator(event_type, **kwargs)] = None

    def create(self, *args, **kwargs):
        return self.model.create(*args, **kwargs)  # type: ignore

    @RepositoryDecorators.event_gatherer
    def _add(self, model):
        self.session.add(model)
        return model

    def _add_all(self, models):
        self.session.add_all(models)
        return models

    @RepositoryDecorators.event_gatherer
    async def _get(self, is_update):
        if is_update:
            q = await self.session.execute(self._base_query.with_for_update().limit(1))
        else:
            q = await self.session.execute(self._base_query.limit(1))
        return q.scalars().first()

    async def _list(
        self,
        *,
        is_update,
        scalar=True,
    ):
        if is_update:
            q = await self.session.execute(self._base_query.with_for_update())
        else:
            q = await self.session.execute(self._base_query)
        if scalar:
            return q.scalars().all()
        else:
            return q.all()

    def _add_up_events(self, model):
        while model.events:
            event = model.events.popleft()
            self.events[event] = None


class AsyncSqlAlchemyViewRepository(Generic[ModelType], SqlAlchemyRepository):
    def __init__(self, *, model: Type[ModelType], session: AsyncSession):
        super().__init__(model=model, session=session)
        # self.load_aggregate()

    @RepositoryDecorators.query_resetter
    async def get(self, is_update=False):
        return await self._get(is_update=is_update)

    @RepositoryDecorators.query_resetter
    async def list(self, scalar=True, is_update=False):
        return await self._list(scalar=scalar, is_update=is_update)

    async def _get(self, is_update):
        if is_update:
            q = await self.session.execute(self._base_query.with_for_update().limit(1))
        else:
            q = await self.session.execute(self._base_query.limit(1))
        return q.scalars().first()

    async def _list(
        self,
        *,
        is_update,
        scalar=True,
    ):
        if is_update:
            q = await self.session.execute(self._base_query.with_for_update())
        else:
            q = await self.session.execute(self._base_query)
        if scalar:
            return q.scalars().all()
        else:
            return q.all()

    def _add(self, model):
        raise Exceptions.InvalidOperation

    def _add_all(self, models):
        raise Exceptions.InvalidOperation

    # TODO: deprecate after CQRS
    def _get_ordering_fields(self, ordering: str):
        """
        regular ordering
        1. first check desc or asc by checking '-'
        2. check if ordering on nested json
            col_name_json_check > implements nested json field ordering
        """
        ordering_list = ordering.split(",")
        ordering_fields = []
        default_ordering_by_create_dt = getattr(self.model, "create_dt")
        for col_name in ordering_list:
            if col_name:
                desc = False
                if col_name.startswith("-"):
                    desc = True
                    col_name = col_name[1:]
                col_name_json_check = col_name.split("__")
                model_column = getattr(self.model, col_name_json_check[0])
                if len(col_name_json_check) == 2:
                    model_column = model_column[col_name_json_check[1]]
                if desc:
                    ordering_fields.append(model_column.desc())
                else:
                    ordering_fields.append(model_column.asc())

        # Default: create_dt.desc()
        if not ordering_fields:
            ordering_fields.append(default_ordering_by_create_dt.desc())
        return ordering_fields

    def paginate(self, page, items_per_page):
        self._base_query = self._base_query.offset((page - 1) * items_per_page).limit(items_per_page)
        return self

    def order_by(self, criteria):
        if criteria is not None:
            ordering_fields = self._get_ordering_fields(criteria)
            self._base_query = self._base_query.order_by(*ordering_fields)
        return self

    async def count(self, offset: int = 0):
        # TODO: someday if we don't use "id" may chage logic like "func.count(1)"
        query = self._base_query.with_only_columns([func.count(self.model.id)]).order_by(None)  # type: ignore
        q = await self.session.scalar(query.offset(offset).limit(None))
        if not q:
            q = 0
        return q

    def _query_reset(self):
        self._base_query = select(self.model)
