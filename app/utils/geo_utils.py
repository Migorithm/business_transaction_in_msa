from decimal import Decimal
from enum import IntEnum
from functools import reduce
from typing import Any, Sequence


class RegionId(IntEnum):
    MAINLAND = 1
    JEJU = 2
    OUTSIDE_JEJU = 3


division2_dict = {"jeju": (63000, 63644)}
division3_dict = {
    "incheon_jungu_islands": (22386, 22388),
    "incheon_ganghwa_islands": (23004, 23010),
    "incheon_ongjin_islands1": (23100, 23116),
    "incheon_ongjin_islands2": (23124, 23136),
    "chungnam_dangjin_islands": (31708),
    "chungnam_taean_islands": (32133),
    "chungnam_boryung_islands": (33411),
    "kyunbook_ulleungdo": (40200, 40240),
    "busan_gangseogu_islands": (46768, 46771),
    "kyungnam_sacheon_islands": (52570, 52571),
    "kyungnam_tongyeong_islands1": (53031, 53033),
    "kyungnam_tongyeong_islands2": (53089, 53104),
    "kyungnam_tongyeong_islands3": (54000),
    "jeonbuk_buan_islands": (56347, 56349),
    "jeonnam_yeonggwang_islands": (57068, 57069),
    "jeonnam_mokpo_islands": (58760, 58762),
    "jeonnam_shinan_islands1": (58800, 58810),
    "jeonnam_shinan_islands2": (58816, 58818),
    "jeonnam_shinan_islands3": (28826),
    "jeonnam_shinan_islands4": (58828, 58866),
    "jeonnam_jindo_islands": (58953, 58958),
    "jeonnam_wando_islands1": (59102, 59103),
    "jeonnam_wando_islands2": (59106),
    "jeonnam_wando_islands3": (59127),
    "jeonnam_wando_islands4": (59129),
    "jeonnam_wando_islands5": (59137, 59166),
    "jeonnam_yeosu_islands1": (59650),
    "jeonnam_yeosu_islands2": (59766),
    "jeonnam_yeosu_islands3": (59781, 59790),
}


def get_range(range_) -> list[str]:
    if type(range_) is int:
        result = [str(range_)]
    elif type(range_) is str:
        result = [range_]
    elif type(range_) is tuple:
        result = list(map(str, range(*range_))) + [str(range_[1])]
    return result


division2_values = list(division2_dict.values())
division3_values = list(division3_dict.values())

# turn ranges into a list of lists
division2_ranges_list_of_list = list(map(get_range, division2_values))
division3_ranges_list_of_list = list(map(get_range, division3_values))

# flatten list of lists into a list
division2_ranges = reduce(lambda x, y: x + y, division2_ranges_list_of_list)
division3_ranges = reduce(lambda x, y: x + y, division3_ranges_list_of_list)


def calculate_region_additional_delivery_fee(
    region_id: RegionId,
    region_division_level: int | None,
    delivery_info: dict,
) -> Decimal:
    region_additional_delivery_fee = Decimal("0")

    if delivery_info["is_additional_pricing_set"]:
        if region_division_level is None:
            region_additional_delivery_fee = Decimal("0")
        elif region_division_level == 2:
            if region_id == RegionId.MAINLAND:
                region_additional_delivery_fee = Decimal("0")
            else:
                region_additional_delivery_fee = Decimal(str(delivery_info["division2_fee"]))
        else:
            if region_id == RegionId.MAINLAND:
                region_additional_delivery_fee = Decimal("0")
            elif region_id == RegionId.JEJU:
                region_additional_delivery_fee = Decimal(str(delivery_info["division3_jeju_fee"]))
            else:
                region_additional_delivery_fee = Decimal(str(delivery_info["division3_outside_jeju_fee"]))

    return region_additional_delivery_fee


def determine_area(postal_code: str) -> RegionId:
    if binary_search_on_postal_code(division2_ranges, 0, len(division2_ranges) - 1, postal_code):
        return RegionId.JEJU
    elif binary_search_on_postal_code(division3_ranges, 0, len(division3_ranges) - 1, postal_code):
        return RegionId.OUTSIDE_JEJU
    return RegionId.MAINLAND


def binary_search_on_postal_code(arr: Sequence, low: int, high: int, x: Any):
    # Check base case
    # postal code might be string
    # same type should be used for operators (+, - ...)
    if high >= low:
        mid = (high + low) // 2
        if str(arr[mid]) == x:
            return True

        # If element is smaller than mid, then it can only
        # be present in left subarray
        elif str(arr[mid]) > x:
            return binary_search_on_postal_code(arr, low, mid - 1, x)

        # Else the element can only be present in right subarray
        else:
            return binary_search_on_postal_code(arr, mid + 1, high, x)

    else:
        # Element is not present in the list
        return False
