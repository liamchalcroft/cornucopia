from types import GeneratorType as generator
from typing import List
import torch
from torch import Tensor


def ensure_list(x, size=None, crop=True, **kwargs):
    """Ensure that an object is a list (of size at last dim)

    If x is a list, nothing is done (no copy triggered).
    If it is a tuple, it is converted into a list.
    Otherwise, it is placed inside a list.
    """
    if not isinstance(x, (list, tuple, range, generator)):
        x = [x]
    elif not isinstance(x, list):
        x = list(x)
    if size and len(x) < size:
        default = kwargs.get('default', x[-1] if x else None)
        x += [default] * (size - len(x))
    if size and crop:
        x = x[:size]
    return x


def make_vector(input, n=None, crop=True, *args,
                dtype=None, device=None, **kwargs):
    """Ensure that the input is a (tensor) vector and pad/crop if necessary.

    Parameters
    ----------
    input : scalar or sequence or generator
        Input argument(s).
    n : int, optional
        Target length.
    crop : bool, default=True
        Crop input sequence if longer than `n`.
    default : optional
        Default value to pad with.
        If not provided, replicate the last value.
    dtype : torch.dtype, optional
        Output data type.
    device : torch.device, optional
        Output device

    Returns
    -------
    output : tensor
        Output vector.

    """
    input = torch.as_tensor(input, dtype=dtype, device=device).flatten()
    if n is None:
        return input
    if n is not None and input.numel() >= n:
        return input[:n] if crop else input
    if args:
        default = args[0]
    elif 'default' in kwargs:
        default = kwargs['default']
    else:
        default = input[-1]
    default = input.new_full([n-len(input)], default)
    return torch.cat([input, default])


def cumprod(sequence, reverse=False, exclusive=False):
    """Perform the cumulative product of a sequence of elements.

    Parameters
    ----------
    sequence : any object that implements `__iter__`
        Sequence of elements for which the `__mul__` operator is defined.
    reverse : bool, default=False
        Compute cumulative product from right-to-left:
        `cumprod([a, b, c], reverse=True) -> [a*b*c, b*c, c]`
    exclusive : bool, default=False
        Exclude self from the cumulative product:
        `cumprod([a, b, c], exclusive=True) -> [1, a, a*b]`

    Returns
    -------
    product : list
        Product of the elements in the sequence.

    """
    if reverse:
        sequence = reversed(sequence)
    accumulate = None
    seq = [1] if exclusive else []
    for elem in sequence:
        if accumulate is None:
            accumulate = elem
        else:
            accumulate = accumulate * elem
        seq.append(accumulate)
    if exclusive:
        seq = seq[:-1]
    if reverse:
        seq = list(reversed(seq))
    return seq


def cumsum(sequence, reverse=False, exclusive=False):
    """Perform the cumulative sum of a sequence of elements.

    Parameters
    ----------
    sequence : any object that implements `__iter__`
        Sequence of elements for which the `__sum__` operator is defined.
    reverse : bool, default=False
        Compute cumulative product from right-to-left:
        `cumprod([a, b, c], reverse=True) -> [a+b+c, b+c, c]`
    exclusive : bool, default=False
        Exclude self from the cumulative product:
        `cumprod([a, b, c], exclusive=True) -> [0, a, a+b]`

    Returns
    -------
    sum : list
        Sum of the elements in the sequence.

    """
    if reverse:
        sequence = reversed(sequence)
    accumulate = None
    seq = [0] if exclusive else []
    for elem in sequence:
        if accumulate is None:
            accumulate = elem
        else:
            accumulate = accumulate + elem
        seq.append(accumulate)
    if exclusive:
        seq = seq[:-1]
    if reverse:
        seq = list(reversed(seq))
    return seq


def _compare_versions(version1, mode, version2):
    for v1, v2 in zip(version1, version2):
        if mode in ('gt', '>'):
            if v1 > v2:
                return True
            elif v1 < v2:
                return False
        elif mode in ('ge', '>='):
            if v1 > v2:
                return True
            elif v1 < v2:
                return False
        elif mode in ('lt', '<'):
            if v1 < v2:
                return True
            elif v1 > v2:
                return False
        elif mode in ('le', '<='):
            if v1 < v2:
                return True
            elif v1 > v2:
                return False
    if mode in ('gt', 'lt', '>', '<'):
        return False
    else:
        return True


def torch_version(mode, version):
    """Check torch version

    Parameters
    ----------
    mode : {'<', '<=', '>', '>='}
    version : tuple[int]

    Returns
    -------
    True if "torch.version <mode> version"

    """
    current_version, *cuda_variant = torch.__version__.split('+')
    major, minor, patch, *_ = current_version.split('.')
    # strip alpha tags
    for x in 'abcdefghijklmnopqrstuvwxy':
        if x in patch:
            patch = patch[:patch.index(x)]
    current_version = (int(major), int(minor), int(patch))
    version = ensure_list(version)
    return _compare_versions(current_version, mode, version)


if torch_version('>=', (1, 10)):
    @torch.jit.script
    def meshgrid_script_ij(x: List[torch.Tensor]) -> List[Tensor]:
        return torch.meshgrid(x, indexing='ij')
    @torch.jit.script
    def meshgrid_script_xy(x: List[torch.Tensor]) -> List[Tensor]:
        return torch.meshgrid(x, indexing='xy')
    meshgrid_ij = lambda *x: torch.meshgrid(*x, indexing='ij')
    meshgrid_xy = lambda *x: torch.meshgrid(*x, indexing='xy')
else:
    @torch.jit.script
    def meshgrid_script_ij(x: List[torch.Tensor]) -> List[Tensor]:
        return torch.meshgrid(x)
    @torch.jit.script
    def meshgrid_script_xy(x: List[torch.Tensor]) -> List[Tensor]:
        grid = torch.meshgrid(x)
        if len(grid) > 1:
            grid[0] = grid[0].transpose(0, 1)
            grid[1] = grid[1].transpose(0, 1)
        return grid
    meshgrid_ij = lambda *x: torch.meshgrid(*x)
    def meshgrid_xy(*x):
        grid = list(torch.meshgrid(*x))
        if len(grid) > 1:
            grid[0] = grid[0].transpose(0, 1)
            grid[1] = grid[1].transpose(0, 1)
        return grid


def cartesian_grid(shape, **backend):
    """Wrapper for meshgrid(arange(...))

    Parameters
    ----------
    shape : list[int]

    Returns
    -------
    list[Tensor]

    """
    return meshgrid_ij(*(torch.arange(s, **backend) for s in shape))


def move_to_permutation(length, source, destination):

    source = ensure_list(source)
    destination = ensure_list(destination)
    if len(destination) == 1:
        # we assume that the user wishes to keep moved dimensions
        # in the order they were provided
        destination = destination[0]
        if destination >= 0:
            destination = list(range(destination, destination+len(source)))
        else:
            destination = list(range(destination+1-len(source), destination+1))
    if len(source) != len(destination):
        raise ValueError('Expected as many source as destination positions.')
    source = [length + src if src < 0 else src for src in source]
    destination = [length + dst if dst < 0 else dst for dst in destination]
    if len(set(source)) != len(source):
        raise ValueError(f'Expected source positions to be unique but got '
                         f'{source}')
    if len(set(destination)) != len(destination):
        raise ValueError(f'Expected destination positions to be unique but got '
                         f'{destination}')

    # compute permutation
    positions_in = list(range(length))
    positions_out = [None] * length
    for src, dst in zip(source, destination):
        positions_out[dst] = src
        positions_in[src] = None
    positions_in = filter(lambda x: x is not None, positions_in)
    for i, pos in enumerate(positions_out):
        if pos is None:
            positions_out[i], *positions_in = positions_in

    return positions_out


def movedims(input, source, destination):
    """Moves the position of one or more dimensions

    Other dimensions that are not explicitly moved remain in their
    original order and appear at the positions not specified in
    destination.

    Parameters
    ----------
    input : tensor
        Input tensor
    source : int or sequence[int]
        Initial positions of the dimensions
    destination : int or sequence[int]
        Output positions of the dimensions.

        If a single destination is provided:
        - if it is negative, the last source dimension is moved to
          `destination` and all other source dimensions are moved to its left.
        - if it is positive, the first source dimension is moved to
          `destination` and all other source dimensions are moved to its right.

    Returns
    -------
    output : tensor
        Tensor with moved dimensions.

    """
    perm = move_to_permutation(input.dim(), source, destination)
    return input.permute(*perm)


def remainder(x, d):
    return x - (x // d) * d


def sub2ind(sub: List[int], shape: List[int]) -> int:
    """Convert sub indices (i, j, k) into linear indices.
    The rightmost dimension is the most rapidly changing one
    -> if shape == [D, H, W], the strides are therefore [H*W, W, 1]
    Parameters
    ----------
    sub : list[int]
    shape : list[int]
    Returns
    -------
    ind : int
    """
    *sub, ind = sub
    stride = cumprod(shape[1:], reverse=True)
    for i, s in zip(sub, stride):
        ind += i * s
    return ind


def ind2sub(ind: int, shape: List[int]) -> List[int]:
    """Convert linear indices into sub indices (i, j, k).
    The rightmost dimension is the most rapidly changing one
    -> if shape == [D, H, W], the strides are therefore [H*W, W, 1]
    Parameters
    ----------
    ind : int
    shape : list[int]
    Returns
    -------
    sub : list[int]
    """
    stride = list(cumprod(shape, reverse=True, exclusive=True))
    sub: List[int] = [ind] * len(shape)
    for d in range(len(shape)):
        if d > 0:
            sub[d] = remainder(sub[d], stride[d-1])
        sub[d] = sub[d] // stride[d]
    return sub
