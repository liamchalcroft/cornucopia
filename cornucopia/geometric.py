import torch
import math
import interpol
from .base import Transform, RandomizedTransform
from .random import Sampler, Uniform, RandInt
from .utils import warps
from .utils.py import ensure_list


__all__ = ['ElasticTransform', 'RandomElasticTransform', 'AffineTransform',
           'RandomAffineTransform', 'MakeAffinePair']


class ElasticTransform(Transform):
    """
    Elastic transform encoded by cubic splines.
    The number of control points is fixed but coefficients are
    randomly sampled.
    """

    def __init__(self, dmax=0.1, unit='fov', shape=5, bound='border',
                 shared=True):
        """

        Parameters
        ----------
        dmax : [list of] float
            Max displacement per dimension
        unit : {'fov', 'vox'}
            Unit of `dmax`.
        shape : [list of] int
            Number of spline control points
        bound : {'zeros', 'border', 'reflection'}
            Padding mode
        shared : bool
            Apply same transform to all images/channels
        """
        super().__init__(shared=shared)
        if unit not in ('fov', 'vox'):
            raise ValueError('Unit must be one of {"fov", "vox"} '
                             f'but got "{unit}".')
        if bound not in ('zeros', 'border', 'reflection'):
            raise ValueError('Bound must be one of '
                             '{"zeros", "border", reflection"} '
                             f'but got "{bound}".')
        self.dmax = dmax
        self.unit = unit
        self.bound = bound
        self.shape = shape

    def get_parameters(self, x):
        batch, *fullshape = x.shape
        ndim = len(fullshape)
        smallshape = ensure_list(self.shape, ndim)
        dmax = ensure_list(self.dmax, ndim)
        backend = dict(dtype=x.dtype, device=x.device)
        if not backend['dtype'].is_floating_point:
            backend['dtype'] = torch.get_default_dtype()
        if self.unit == 'fov':
            dmax = [d * f for d, f in zip(dmax, fullshape)]
        t = torch.rand([batch, ndim, *smallshape], **backend)
        for d in range(ndim):
            t[:, d].sub_(0.5).mul_(2*dmax[d])
        ft = interpol.resize(t, shape=fullshape, interpolation=3,
                             prefilter=False)
        return ft, t

    def transform_with_parameters(self, x, parameters):
        flow, controls = parameters
        x = warps.apply_flow(x[:, None], flow.movedim(1, -1),
                             padding_mode=self.bound)
        return x[:, 0]


class RandomElasticTransform(RandomizedTransform):
    """
    Elastic Transform with random parameters.
    """

    def __init__(self, dmax=0.3, shape=10,
                 unit='fov', bound='border', shared=True):
        """

        Parameters
        ----------
        dmax : Sampler or float
            Sampler or Upper bound for maximum displacement
        shape : Sampler or int
            Sampler or Upper bounds for number of control points
        unit : {'fov', 'vox'}
            Unit of `dmax`
        bound : {'zeros', 'border', 'reflection'}
            Padding mode
        shared : bool
            Apply same transform to all images/channels
        """
        if not isinstance(dmax, Sampler):
            dmax = (0, dmax)
        if not isinstance(shape, Sampler):
            shape = (2, shape)

        self._sample = dict(dmax=Uniform.make(dmax), shape=RandInt.make(shape))
        super().__init__(self._build, self._sample, shared=shared)
        self.unit = unit
        self.bound = bound

    def _build(self, dmax, shape):
        return ElasticTransform(dmax=dmax, shape=shape,
                                unit=self.unit, bound=self.bound)


class AffineTransform(Transform):
    """
    Apply an affine transform encoded by translations, rotations,
    shears and zooms.

    The affine matrix is defined as:
        A = T @ Rx @ Ry @ Rz @ Sx @ Sy Sz @ Z
    with the center of the field of view used as center of rotation.
    (A si a matrix so the transforms are applied right to left)
    """

    def __init__(self, translations=0, rotations=0, shears=0, zooms=0,
                 unit='fov', bound='border', shared=True):
        """

        Parameters
        ----------
        translations : [list of] float
            Translation (per X/Y/Z)
        rotations : [list of] float
            Rotations (about Z/Y/X), in deg
        shears : [list of] float
            Translation (about Z/Y/Z)
        zooms : [list of] float
            Zoom about 1 (per X/Y/Z)
        unit : {'fov', 'vox'}
            Unit of `translations`.
        bound : {'zeros', 'border', 'reflection'}
            Padding mode
        shared : bool
            Apply same transform to all images/channels
        """
        super().__init__(shared=shared)
        if unit not in ('fov', 'vox'):
            raise ValueError('Unit must be one of {"fov", "vox"} '
                             f'but got "{unit}".')
        if bound not in ('zeros', 'border', 'reflection'):
            raise ValueError('Bound must be one of '
                             '{"zeros", "border", reflection"} '
                             f'but got "{bound}".')
        self.translations = translations
        self.rotations = rotations
        self.zooms = zooms
        self.shears = shears
        self.unit = unit
        self.bound = bound

    def get_parameters(self, x):
        batch, *fullshape = x.shape
        ndim = len(fullshape)
        backend = dict(dtype=x.dtype, device=x.device)
        if not backend['dtype'].is_floating_point:
            backend['dtype'] = torch.get_default_dtype()

        rotations = ensure_list(self.rotations, ndim * (ndim - 1) // 2)
        shears = ensure_list(self.shears, ndim * (ndim - 1) // 2)
        translations = ensure_list(self.translations, ndim)
        zooms = ensure_list(self.zooms, ndim)
        offsets = [(n-1)/2 for n in fullshape]

        if self.unit == 'fov':
            translations = [t * n for t, n in zip(translations, fullshape)]
        rotations = [r * math.pi / 180 for r in rotations]

        rotations = torch.as_tensor(rotations, **backend)
        shears = torch.as_tensor(shears, **backend)
        translations = torch.as_tensor(translations, **backend)
        zooms = torch.as_tensor(zooms, **backend)
        offsets = torch.as_tensor(offsets, **backend)

        I = torch.eye(ndim+1, **backend)
        O = I.clone()
        O[:ndim, -1] = -offsets
        Z = I.clone()
        Z.diagonal(0, -1, -2)[:-1].copy_(1 + zooms)
        T = torch.eye(ndim+1, **backend)
        T[:ndim, -1] = translations

        A = O               # origin at center of FOV
        A = Z @ A           # zoom
        if ndim == 2:
            S = I.clone()
            S[0, 1] = S[1, 0] = shears[0]
            A = S @ A       # shear
            R = I.clone()
            R[0, 0] = R[1, 1] = rotations[0].cos()
            R[0, 1] = rotations[0].sin()
            R[1, 0] = -R[0, 1]
            A = R @ A       # rotation
        elif ndim == 3:
            Sz = I.clone()
            Sz[0, 1] = Sz[1, 0] = shears[0]
            Sy = I.clone()
            Sy[0, 2] = Sz[2, 0] = shears[1]
            Sx = I.clone()
            Sx[1, 2] = Sz[2, 1] = shears[2]
            A = Sx @ Sy @ Sz @ A       # shear
            Rz = I.clone()
            Rz[0, 0] = Rz[1, 1] = rotations[0].cos()
            Rz[0, 1] = rotations[0].sin()
            Rz[1, 0] = -Rz[0, 1]
            Ry = I.clone()
            Ry[0, 0] = Ry[2, 2] = rotations[1].cos()
            Ry[0, 2] = rotations[1].sin()
            Ry[2, 0] = -Ry[0, 2]
            Rx = I.clone()
            Rx[1, 1] = Rx[2, 2] = rotations[2].cos()
            Rx[1, 2] = rotations[2].sin()
            Rx[2, 1] = -Rx[1, 2]
            A = Rx @ Ry @ Rz @ A       # rotation
        A = O.inverse() @ A
        A = T @ A

        t = warps.affine_flow(A, fullshape).movedim(-1, 0)
        return t, A

    def transform_with_parameters(self, x, parameters):
        flow, matrix = parameters
        x = warps.apply_flow(x[:, None], flow.movedim(0, -1),
                             padding_mode=self.bound)
        return x[:, 0]


class RandomAffineTransform(RandomizedTransform):
    """
    Affine Transform with random parameters.
    """

    def __init__(self,
                 translations=0.1,
                 rotations=15,
                 shears=0.012,
                 zooms=0.15,
                 unit='fov', bound='border', shared=True):
        """

        Parameters
        ----------
        translations : Sampler or [list of] float
            Sampler or Upper bound for translation (per X/Y/Z)
        rotations : Sampler or [list of] float
            Sampler or Upper bound for rotations (about Z/Y/X), in deg
        shears : Sampler or [list of] float
            Sampler or Upper bound for shears (about Z/Y/Z)
        zooms : Sampler or [list of] float
            Sampler or Upper bound for zooms about 1 (per X/Y/Z)
        unit : {'fov', 'vox'}
            Unit of `translations`.
        bound : {'zeros', 'border', 'reflection'}
            Padding mode
        shared : bool
            Apply same transform to all images/channels
        """
        def to_range(vmax):
            if not isinstance(vmax, Sampler):
                if isinstance(vmax, (list, tuple)):
                    vmax = ([-v for v in vmax], vmax)
                else:
                    vmax = (-vmax, vmax)
            return vmax

        self._sample = dict(translations=Uniform.make(to_range(translations)),
                            rotations=Uniform.make(to_range(rotations)),
                            shears=Uniform.make(to_range(shears)),
                            zooms=Uniform.make(to_range(zooms)))
        super().__init__(self._build, self._sample, shared=shared)
        self.unit = unit
        self.bound = bound

    def get_parameters(self, x):
        ndim = x.dim() - 1
        if isinstance(self.sample, (list, tuple)):
            return self.subtransform(*[f(ndim) for f in self.sample])
        if hasattr(self.sample, 'items'):
            return self.subtransform(**{k: f(ndim) for k, f in self.sample.items()})
        return self.subtransform(self.sample(ndim))

    def _build(self, translations, rotations, shears, zooms):
        return AffineTransform(translations=translations,
                               rotations=rotations,
                               shears=shears,
                               zooms=zooms,
                               unit=self.unit,
                               bound=self.bound)


class MakeAffinePair(Transform):
    """
    Generate a pair made of the same image transformed in two different ways.

    This Transform returns a tuple: (transformed_input, true_transform),
    where transformed_input has the same layout as the input and
    true_transform is a dictionary with keys 'flow' and 'affine'.
    """

    def __init__(self, transform=None):
        super().__init__(shared=True)
        self.subtransform = transform or RandomAffineTransform()

    def get_parameters(self, x):
        t1 = self.subtransform.get_parameters(x)
        t2 = self.subtransform.get_parameters(x)
        p1, p2 = t1.get_parameters(x), t2.get_parameters(x)
        return t1, p1, t2, p2

    def transform_with_parameters(self, x, parameters):
        t1, p1, t2, p2 = parameters
        x1 = t1.transform_with_parameters(x, p1)
        x2 = t2.transform_with_parameters(x, p2)
        return x1, x2

    def forward(self, *x):
        numel = len(x)
        x0 = self.get_first_element(x)
        theta = self.get_parameters(x0)
        x = self.forward_with_parameters(*x, parameters=theta)
        if numel == 1: x = (x,)

        _, (flow1, mat1), _, (flow2, mat2) = theta
        flow12 = flow1 - flow2
        mat12 = mat2.inverse() @ mat1

        return (*x, dict(flow=flow12, affine=mat12))
