from .IsNotSuspended import IsNotSuspended
from .IsOwner import IsOwner, IsOwnerOrReadOnly
from .StrictModelPermission import StrictModelPermission

__all__ = [
    "IsNotSuspended",
    "IsOwner",
    "IsOwnerOrReadOnly",
    "StrictModelPermission",
]
