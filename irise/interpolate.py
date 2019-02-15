import numpy as np
import iris
import iris.analysis
import iris.cube
import iris.coords
import iris.util

from irise import grid
from irise.fortran import interpolate as finterpolate


def interpolate(cube, interpolator=iris.analysis.Linear, extrapolation_mode='linear',
         **kwargs):
    """Interpolates to the given coordinates

    Works as a wrapper function to :py:func:`iris.cube.Cube.interpolate`

    Example:

        >>> newcube = interpolate(cube, longitude=0, latitude=45)

    Args:
        cube (iris.cube.Cube):

        interpolator (optional): Instance of the iris interpolator to use.
            Default is :py:class:`iris.analysis.Linear`

        extrapolation_mode (optional): The extrapolation mode for iris to use
            in the case of data outside the co-ordinate bounds. Default is
            linear

        **kwargs: Provides the coordinate value pairs to be interpolated to.

    Returns:
        iris.cube.Cube:
    """
    # Extract the specified output co-ordinates
    points = [(coord, kwargs[coord]) for coord in kwargs]

    # Call the cube's built in interpolation method
    newcube = cube.interpolate(points, interpolator(
                               extrapolation_mode=extrapolation_mode))
    return newcube


def cross_section(cube, xs, xf, ys, yf, npoints,
                  interpolator=iris.analysis.Linear,
                  extrapolation_mode='linear'):
    """ Interpolate a cross section between (xs, ys) and (xf, yf)

    Args:
        cube (iris.cube.Cube): Must be 3D (z,y,x)

        xs (float): Start point of x-coordinate

        xf (float): End point of x-coordinate

        ys (float): Start point of y-coordinate

        yf (float): End point of y-coordinate

        npoints (int, optional): Number of points to interpolate to along the
            cross-section

        interpolator (optional): Instance of the iris interpolator to use.
            Default is :py:class:`iris.analysis.Linear`

        extrapolation_mode (optional): The extrapolation mode for iris to use
            in the case of data outside the co-ordinate bounds. Default is
            linear

    Returns:
        iris.cube.Cube: A 2D cube of the vertical cross-section along the given
        points
    """
    # Create arrays for the set of points along the cross-section
    xpoints = np.linspace(xs, xf, npoints)
    ypoints = np.linspace(ys, yf, npoints)

    # Extract the names of the x and y co-ordinates
    xcoord = cube.coord(axis='X').name()
    ycoord = cube.coord(axis='Y').name()

    # Call the cube's built in interpolation method
    newcube = cube.interpolate([(xcoord, xpoints), (ycoord, ypoints)],
                               interpolator(
                               extrapolation_mode=extrapolation_mode))

    # The interpolation returns a box with all corresponding xpoints and
    # ypoints (i.e. a 3d cube). We need to extract the diagonal line along this
    # box to return a 2d cube
    # Demote the y co-ordinate to an auxiliary coord prior to reducing the
    # shape
    iris.util.demote_dim_coord_to_aux_coord(newcube, ycoord)

    # Take the diagonal line along the 3d cube. Use the cubelist functionality
    # to reduce this to a single cube
    newcubelist = iris.cube.CubeList()
    for i in range(npoints):
        try:
            newcubelist.append(newcube[:, i, i])
        except IndexError:
            # Allow 2d cubes to be interpolated
            newcubelist.append(newcube[i, i])

    # Reduce to a single cube. This currently has the side effect of always
    # making the y coordinate the 1st dimension and the z coordinate the 2nd
    # dimension. Still plots OK though
    newcube = newcubelist.merge()[0]

    return newcube


def to_level(cube, order=0, **kwargs):
    """ Interpolates to the vertical co-ordinate level

    Args:
        cube (iris.cube.Cube):

        order (int): Order of interpolation. Currently only supports linear (1).

        **kwargs: Provides the coordinate value pair to be interpolated to. Must
            be specified as a list.

            e.g. to interpolate a cube onto a vertical surface of 1000m

            >>> to_level(cube, altitude=[1000])

    Returns:
        iris.cube.Cube: A cube interpolated onto the new vertical co-ordinate.
        Has the same properties as the input cube but with new vertical
        co-ordinates
    """
    if len(kwargs) > 1:
        raise Exception('Can only specify a single vertical co-ordinate')

    # Extract the specified output co-ordinate information
    coord_name = list(kwargs)[0]
    coord_in = cube.coord(coord_name)
    coord_out = kwargs[coord_name]

    # Broadcast array to cube shape
    dims = np.ndim(coord_out)
    if dims == 1:
        ny, nx = cube.shape[1:]
        coord_out_3d = coord_out * np.ones([nx, ny, len(coord_out)])
        coord_out_3d = coord_out_3d.transpose()
    elif dims == 3:
        coord_out_3d = coord_out

    else:
        raise Exception('Coordinate must be 3d or a list of levels')

    # Select the interpolation flag based on the coordinate
    if 'pressure' in coord_name:
        # Air pressure is interpolated logarithmically
        interp_flag = 1
    else:
        # Otherwise interpolation is linear
        interp_flag = 0

    # Interpolate data
    newdata, mask = finterpolate.to_level(
        cube.data, coord_in.points, coord_out_3d, interp_flag, order)
    newdata = np.ma.masked_where(mask, newdata)

    # Create a new cube with the new number of vertical levels
    newcube = iris.cube.Cube(
        newdata, long_name=cube.name(), units=cube.units,
        attributes=cube.attributes,
        dim_coords_and_dims=[(grid.extract_dim_coord(cube, 'y'), 1),
                             (grid.extract_dim_coord(cube, 'x'), 2)])

    # Add the new co-ordinate to the output cube
    newcoord = iris.coords.AuxCoord(
        coord_out, long_name=coord_name, units=coord_in.units)
    newcube.add_aux_coord(newcoord, range(newcoord.ndim))

    # Promote single dimensional coordinates to dimensional coordinates
    try:
        iris.util.promote_aux_coord_to_dim_coord(newcube, coord_name)
    except ValueError:
        dummy_coord = iris.coords.DimCoord(range(len(coord_out)),
                               long_name='level_number')
        newcube.add_dim_coord(dummy_coord, 0)

    # Add single value coordinates back to the newcube
    add_scalar_coords(cube, newcube)

    return newcube


def add_scalar_coords(cube, newcube):
    for coord in cube.aux_coords:
        if len(coord.points) == 1:
            newcube.add_aux_coord(coord)


def remap_3d(cube, target, vert_coord=None):
    """Remap one cube on to the target mapping

    Args:
        cube (iris.cube.Cube): The cube to be re-mapped

        target (iris.cube.Cube): The cube to re-map to

        vert_coord (str, optional): The name of the coordinate for the vertical
            re-mapping to be done on. Default is None and will use the DimCoord
            for the z-axis

    Returns:
        iris.cube.Cube:
    """
    # Regrid in the horizontal
    cube = cube.regrid(target, iris.analysis.Linear())

    # Interpolate in the vertical
    if vert_coord is None:
        z = grid.extract_dim_coord(target, 'z')
    else:
        z = target.coord(vert_coord)
    cube = cube.interpolate([(z.name(), z.points)], iris.analysis.Linear())

    # Match coordinate information
    newcube = target.copy(data=cube.data)
    newcube.rename(cube.name())
    newcube.units = cube.units

    # Put back correct time information
    for coord in newcube.aux_coords:
        if iris.util.guess_coord_axis(coord) == 'T':
            newcube.remove_coord(coord)

    for coord in cube.aux_coords:
        if iris.util.guess_coord_axis(coord) == 'T':
            newcube.add_aux_coord(coord)

    return newcube
