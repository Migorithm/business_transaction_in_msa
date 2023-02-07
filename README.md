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