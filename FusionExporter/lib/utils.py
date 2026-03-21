"""Utility functions — unit conversion, coordinate formatting, logging."""

import adsk.core
import math


def log(msg):
    """Write a message to Fusion's Text Commands palette."""
    app = adsk.core.Application.get()
    if app:
        app.log('[FusionExporter] {}'.format(msg))


def cm_to_mm(val):
    """Convert Fusion internal cm to millimeters."""
    return val * 10.0


def cm_to_in(val):
    """Convert Fusion internal cm to inches."""
    return val / 2.54


def cm_to_unit(val, unit):
    """Convert Fusion internal cm to the specified output unit."""
    if unit == 'mm':
        return cm_to_mm(val)
    else:
        return cm_to_in(val)


def format_coord(val, unit):
    """Format a coordinate value with appropriate precision.

    mm: 4 decimal places (0.001mm precision)
    in: 6 decimal places (0.000001" precision)
    """
    if unit == 'mm':
        return '{:.4f}'.format(val)
    else:
        return '{:.6f}'.format(val)


def format_depth(val, unit):
    """Format a cut depth value. Uses fewer decimals for readability."""
    if unit == 'mm':
        # Remove trailing zeros but keep at least one decimal
        formatted = '{:.4f}'.format(val).rstrip('0')
        if formatted.endswith('.'):
            formatted += '0'
        return formatted
    else:
        formatted = '{:.6f}'.format(val).rstrip('0')
        if formatted.endswith('.'):
            formatted += '0'
        return formatted


def points_equal_2d(p1, p2, tolerance=1e-6):
    """Check if two 2D points are approximately equal."""
    return (abs(p1[0] - p2[0]) < tolerance and
            abs(p1[1] - p2[1]) < tolerance)


def distance_2d(p1, p2):
    """Euclidean distance between two 2D points."""
    return math.sqrt((p1[0] - p2[0]) ** 2 + (p1[1] - p2[1]) ** 2)
