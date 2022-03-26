import os
import numpy as np
from PIL import Image, ImageCms
import scipy.ndimage
import scipy.misc
import scipy.stats

from smiler_tools import utils


def save_image(path, image, create_parent=True, uid=None, gid=None):
    if uid is None:
        uid = os.getuid()

    if gid is None:
        gid = os.getgid()

    if create_parent:
        utils.create_dirs_if_none(path, uid=uid, gid=gid)

    scipy.misc.imsave(path, image)
    os.chown(path, uid, gid)


def pre_process(img, options, check_channels=True):
    """Pre-processes images based on options generated from SMILER ParameterMap.

    Args:
        img: A numpy array containing the input image.
    options: A dict generated by SMILER's ParameterMap.
    check_channels: if True, convert output to 3 channels.

    Returns:
    result: ndarray
    """
    color_space = options.get("color_space", "RGB")

    img = np.asarray(img, dtype=np.uint8)

    if color_space not in ["default", "RGB", "gray", "YCbCr", "LAB", "HSV"]:
        raise ValueError("{0} color space is not suppported".format(color_space))

    if color_space == "gray":
        color_space = "L"

    if color_space != "default":
        if color_space == "LAB":
            # Special case, PIL can't convert RGB -> LAB directly.
            img = Image.fromarray(img)

            srgb_p = ImageCms.createProfile("sRGB")
            lab_p = ImageCms.createProfile("LAB")

            rgb2lab = ImageCms.buildTransformFromOpenProfiles(
                srgb_p, lab_p, "RGB", "LAB"
            )
            ImageCms.applyTransform(img, rgb2lab, inPlace=True)
            img = np.array(img)
        else:
            img = Image.fromarray(img).convert(color_space)
            img = np.array(img)

    if color_space == "L":
        img = np.expand_dims(img, 2)  # adding third channel
        img = np.repeat(img, 3, axis=2)  # repeating values

    return img


def _gauss2d(shape=(3, 3), sigma=0.5):
    """
    2D gaussian mask - should give the same result as MATLAB's
    fspecial('gaussian',[shape],[sigma])
    """
    m, n = [(ss - 1.0) / 2.0 for ss in shape]
    y, x = np.ogrid[-m : m + 1, -n : n + 1]
    h = np.exp(-(x * x + y * y) / (2.0 * sigma * sigma))
    h[h < np.finfo(h.dtype).eps * h.max()] = 0
    sumh = h.sum()
    if sumh != 0:
        h /= sumh
    return h


def post_process(img, options):
    """Pre-processes images based on options generated from SMILER ParameterMap.

        Args:
        img: a numpy array containing the model output.
        options: A dict generated by SMILER's ParameterMap.

    Returns:
        result: numpy array
    """
    img = np.asarray(img, dtype=np.uint8)

    center_prior = options.get("center_prior", "default")
    center_prior_prop = options.get("center_prior_prop", 0.2)
    center_prior_scale_first = options.get("center_prior_scale_first", True)
    center_prior_weight = options.get("center_prior_weight", 0.5)

    do_smoothing = options.get("do_smoothing", "default")
    scale_output = options.get("scale_output", "min-max")

    smooth_size = options.get("smooth_size", 9.0)
    smooth_std = options.get("smooth_std", 3.0)
    smooth_prop = options.get("smooth_prop", 0.05)

    scale_min = options.get("scale_min", 0.0)
    scale_max = options.get("scale_max", 1.0)

    if do_smoothing in ("custom", "proportional"):
        if do_smoothing == "custom":
            gauss_filter = _gauss2d(shape=(smooth_size, smooth_size), sigma=smooth_std)
        elif do_smoothing == "proportional":
            sigma = smooth_prop * max(img.shape)

            gauss_filter = _gauss2d(shape=(3 * sigma, 3 * sigma), sigma=sigma)

        img = scipy.ndimage.correlate(img, gauss_filter, mode="constant")

    if center_prior in ("proportional_add", "proportional_mult"):
        if center_prior_scale_first:
            min_val = img.min()
            max_val = img.max()
            img = (1.0 / (max_val - min_val)) * (img - min_val)

        w = img.shape[0]
        h = img.shape[1]

        x = np.linspace(-(w // 2), (w - 1) // 2, w)
        y = np.linspace(-(h // 2), (h - 1) // 2, h)

        prior_mask_x = scipy.stats.norm.pdf(x, 0, w * center_prior_prop)
        prior_mask_y = scipy.stats.norm.pdf(y, 0, h * center_prior_prop)
        prior_mask = np.outer(prior_mask_x, prior_mask_y)

        if center_prior == "proportional_add":
            img = (1.0 - center_prior_weight) * img + center_prior_weight * prior_mask
        elif center_prior == "proportional_mult":
            img = (1.0 - center_prior_weight) * img + center_prior_weight * (
                img * prior_mask
            )

    if scale_output == "min-max":
        img = np.interp(img, (img.min(), img.max()), (scale_min, scale_max))
    elif scale_output == "normalized":
        img = (img - img.mean()) / img.std()
    elif scale_output == "log-density":
        min_val = img.min()
        max_val = img.max()
        img = (1.0 / (max_val - min_val)) * (img - min_val)

        img = np.log(img / img.sum())

    return img
