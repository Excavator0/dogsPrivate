import numpy
from PIL import Image, ImageOps


def generate_shade_array(item, side):
    if side == 0:
        side = "front"
    else:
        side = "back"
    img = Image.open(f"templates/{item}_{side}.png")
    img = img.convert("RGB")
    d = img.getdata()
    shade_array = []
    if item == "shirt":
    # 0 - plain color, 1 - lighter shade, 2 - shade, 3 - outline
        for item in d:

            # change all white (also shades of whites)
            if item[0] in list(range(240, 256)):
                shade_array.append(0)
            elif item[0] in list(range(220, 240)):
                shade_array.append(1)
            elif item[0] in list(range(45, 220)):
                shade_array.append(2)
            else:
                shade_array.append(3)
    elif item == "bag" and side == "back":
        for item in d:
            # change all white
            if item[0] in list(range(0, 50)):
                shade_array.append(3)
            else:
                shade_array.append(0)
    else:
        for item in d:
            # change all white
            if item[0] in list(range(0, 100)):
                shade_array.append(3)
            else:
                shade_array.append(0)

    shade_array = numpy.array(shade_array)
    return shade_array


arrs = {"bag_front": generate_shade_array("bag", 0), "bag_back": generate_shade_array("bag", 1),
        "shirt_front": generate_shade_array("shirt", 0), "shirt_back": generate_shade_array("shirt", 1),
        "flag_front": generate_shade_array("flag", 0), "flag_back": generate_shade_array("flag", 1),
        "cup_front": generate_shade_array("cup", 0), "cup_back": generate_shade_array("cup", 1),
        "cap_front": generate_shade_array("cap", 0), "cap_back": generate_shade_array("cap", 1)}
