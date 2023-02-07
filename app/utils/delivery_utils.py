import logging

import httpx

from app import config

# from app.entrypoints.api_v1.exceptions import APIException, APIExceptionErrorCodes

logger = logging.getLogger(__name__)


delivery_company_in_kr = {
    "Company": [
        {"International": "false", "Name": "CJ대한통운", "Code": "04"},
        {"International": "false", "Name": "한진택배", "Code": "05"},
        {"International": "false", "Name": "롯데택배", "Code": "08"},
        {"International": "false", "Name": "우체국택배", "Code": "01"},
        {"International": "false", "Name": "로젠택배", "Code": "06"},
        {"International": "false", "Name": "일양로지스", "Code": "11"},
        {"International": "true", "Name": "EMS", "Code": "12"},
        {"International": "true", "Name": "DHL", "Code": "13"},
        {"International": "false", "Name": "한덱스", "Code": "20"},
        {"International": "true", "Name": "FedEx", "Code": "21"},
        {"International": "true", "Name": "UPS", "Code": "14"},
        {"International": "true", "Name": "USPS", "Code": "26"},
        {"International": "false", "Name": "대신택배", "Code": "22"},
        {"International": "false", "Name": "경동택배", "Code": "23"},
        {"International": "false", "Name": "합동택배", "Code": "32"},
        {"International": "false", "Name": "CU 편의점택배", "Code": "46"},
        {"International": "false", "Name": "GS Postbox 택배", "Code": "24"},
        {"International": "true", "Name": "TNT Express", "Code": "25"},
        {"International": "false", "Name": "한의사랑택배", "Code": "16"},
        {"International": "false", "Name": "천일택배", "Code": "17"},
        {"International": "false", "Name": "건영택배", "Code": "18"},
        {"International": "true", "Name": "GSMNtoN", "Code": "28"},
        {"International": "true", "Name": "KGL네트웍스", "Code": "30"},
        {"International": "true", "Name": "DHL Global Mail", "Code": "33"},
        {"International": "true", "Name": "i-Parcel", "Code": "34"},
        {"International": "true", "Name": "LX판토스", "Code": "37"},
        {"International": "true", "Name": "ECMS Express", "Code": "38"},
        {"International": "false", "Name": "굿투럭", "Code": "40"},
        {"International": "true", "Name": "GSI Express", "Code": "41"},
        {"International": "true", "Name": "CJ대한통운 국제특송", "Code": "42"},
        {"International": "false", "Name": "애니트랙", "Code": "43"},
        {"International": "false", "Name": "SLX택배", "Code": "44"},
        {"International": "false", "Name": "우리택배(구호남택배)", "Code": "45"},
        {"International": "false", "Name": "우리한방택배", "Code": "47"},
        {"International": "true", "Name": "ACI Express", "Code": "48"},
        {"International": "true", "Name": "A.C.E EXPRESS INC", "Code": "49"},
        {"International": "true", "Name": "GPS Logix", "Code": "50"},
        {"International": "true", "Name": "성원글로벌카고", "Code": "51"},
        {"International": "false", "Name": "농협택배", "Code": "53"},
        {"International": "false", "Name": "홈픽택배", "Code": "54"},
        {"International": "true", "Name": "EuroParcel", "Code": "55"},
        {"International": "true", "Name": "Cway Express", "Code": "57"},
        {"International": "true", "Name": "YJS글로벌(영국)", "Code": "60"},
        {"International": "true", "Name": "은하쉬핑", "Code": "63"},
        {"International": "true", "Name": "YJS글로벌(월드)", "Code": "65"},
        {"International": "true", "Name": "Giant Network Group", "Code": "66"},
        {"International": "true", "Name": "디디로지스", "Code": "67"},
        {"International": "true", "Name": "대림통운", "Code": "69"},
        {"International": "true", "Name": "LOTOS CORPORATION", "Code": "70"},
        {"International": "false", "Name": "IK물류", "Code": "71"},
        {"International": "false", "Name": "성훈물류", "Code": "72"},
        {"International": "true", "Name": "CR로지텍", "Code": "73"},
        {"International": "false", "Name": "용마로지스", "Code": "74"},
        {"International": "false", "Name": "원더스퀵", "Code": "75"},
        {"International": "true", "Name": "LineExpress", "Code": "77"},
        {"International": "false", "Name": "로지스밸리택배", "Code": "79"},
        {"International": "true", "Name": "제니엘시스템", "Code": "81"},
        {"International": "false", "Name": "컬리로지스", "Code": "82"},
        {"International": "true", "Name": "스마트로지스", "Code": "84"},
        {"International": "false", "Name": "풀앳홈", "Code": "85"},
        {"International": "false", "Name": "삼성전자물류", "Code": "86"},
        {"International": "true", "Name": "이투마스(ETOMARS)", "Code": "87"},
        {"International": "false", "Name": "큐런택배", "Code": "88"},
        {"International": "false", "Name": "두발히어로", "Code": "89"},
        {"International": "false", "Name": "위니아딤채", "Code": "90"},
        {"International": "true", "Name": "하이브시티", "Code": "91"},
        {"International": "false", "Name": "지니고 당일배송", "Code": "92"},
        {"International": "true", "Name": "팬스타국제특송(PIEX)", "Code": "93"},
        {"International": "false", "Name": "오늘의픽업", "Code": "94"},
        {"International": "true", "Name": "큐익스프레스", "Code": "95"},
        {"International": "false", "Name": "로지스밸리", "Code": "96"},
        {"International": "true", "Name": "에이씨티앤코아물류", "Code": "97"},
        {"International": "true", "Name": "롯데택배 해외특송", "Code": "99"},
        {"International": "true", "Name": "나은물류", "Code": "100"},
        {"International": "false", "Name": "한샘서비스원 택배", "Code": "101"},
        {"International": "true", "Name": "배송하기좋은날(SHIPNERGY)", "Code": "102"},
        {"International": "false", "Name": "NDEX KOREA", "Code": "103"},
        {"International": "false", "Name": "도도플렉스(dodoflex)", "Code": "104"},
        {"International": "true", "Name": "BRIDGE LOGIS", "Code": "105"},
        {"International": "true", "Name": "허브넷로지스틱스", "Code": "106"},
        {"International": "false", "Name": "LG전자(판토스)", "Code": "107"},
        {"International": "true", "Name": "MEXGLOBAL", "Code": "108"},
        {"International": "true", "Name": "파테크해운항공", "Code": "109"},
        {"International": "false", "Name": "부릉", "Code": "110"},
        {"International": "true", "Name": "SBGLS", "Code": "111"},
        {"International": "false", "Name": "1004홈", "Code": "112"},
        {"International": "false", "Name": "썬더히어로", "Code": "113"},
        {"International": "true", "Name": "캐나다쉬핑", "Code": "114"},
        {"International": "false", "Name": "(주)팀프레시", "Code": "116"},
        {"International": "false", "Name": "롯데칠성", "Code": "118"},
        {"International": "false", "Name": "핑퐁", "Code": "119"},
        {"International": "false", "Name": "발렉스 특수물류", "Code": "120"},
        {"International": "true", "Name": "바바바(bababa)", "Code": "121"},
        {"International": "true", "Name": "BAIMA EXPRESS", "Code": "122"},
        {"International": "false", "Name": "엔티엘피스", "Code": "123"},
        {"International": "true", "Name": "LTL", "Code": "124"},
        {"International": "false", "Name": "GTS로지스", "Code": "125"},
        {"International": "true", "Name": "㈜올타코리아", "Code": "126"},
        {"International": "false", "Name": "로지스팟", "Code": "127"},
        {"International": "true", "Name": "판월드로지스틱㈜", "Code": "128"},
        {"International": "false", "Name": "홈픽 오늘도착", "Code": "129"},
        {"International": "false", "Name": "UFO로지스", "Code": "130"},
        {"International": "false", "Name": "딜리래빗", "Code": "131"},
        {"International": "false", "Name": "지오피", "Code": "132"},
        {"International": "false", "Name": "에이치케이홀딩스", "Code": "134"},
        {"International": "false", "Name": "HTNS", "Code": "135"},
        {"International": "false", "Name": "케이제이티", "Code": "136"},
        {"International": "false", "Name": "더바오", "Code": "137"},
        {"International": "false", "Name": "라스트마일", "Code": "138"},
        {"International": "false", "Name": "오늘회 러쉬", "Code": "139"},
        {"International": "true", "Name": "직구문", "Code": "140"},
        {"International": "true", "Name": "인터로지스", "Code": "141"},
        {"International": "false", "Name": "탱고앤고", "Code": "142"},
        {"International": "false", "Name": "투데이", "Code": "143"},
        {"International": "true", "Name": "큐브플로우(CUBEFLOW)", "Code": "144"},
        {"International": "false", "Name": "직접배송", "Code": "999"},
    ]
}

carrier_code_and_name = {
    "04": "CJ대한통운",
    "05": "한진택배",
    "08": "롯데택배",
    "01": "우체국택배",
    "06": "로젠택배",
    "11": "일양로지스",
    "12": "EMS",
    "13": "DHL",
    "20": "한덱스",
    "21": "FedEx",
    "14": "UPS",
    "26": "USPS",
    "22": "대신택배",
    "23": "경동택배",
    "32": "합동택배",
    "46": "CU 편의점택배",
    "24": "GS Postbox 택배",
    "25": "TNT Express",
    "16": "한의사랑택배",
    "17": "천일택배",
    "18": "건영택배",
    "28": "GSMNtoN",
    "30": "KGL네트웍스",
    "33": "DHL Global Mail",
    "34": "i-Parcel",
    "37": "LX판토스",
    "38": "ECMS Express",
    "40": "굿투럭",
    "41": "GSI Express",
    "42": "CJ대한통운 국제특송",
    "43": "애니트랙",
    "44": "SLX택배",
    "45": "우리택배(구호남택배)",
    "47": "우리한방택배",
    "48": "ACI Express",
    "49": "A.C.E EXPRESS INC",
    "50": "GPS Logix",
    "51": "성원글로벌카고",
    "53": "농협택배",
    "54": "홈픽택배",
    "55": "EuroParcel",
    "57": "Cway Express",
    "60": "YJS글로벌(영국)",
    "63": "은하쉬핑",
    "65": "YJS글로벌(월드)",
    "66": "Giant Network Group",
    "67": "디디로지스",
    "69": "대림통운",
    "70": "LOTOS CORPORATION",
    "71": "IK물류",
    "72": "성훈물류",
    "73": "CR로지텍",
    "74": "용마로지스",
    "75": "원더스퀵",
    "77": "LineExpress",
    "79": "로지스밸리택배",
    "81": "제니엘시스템",
    "82": "컬리로지스",
    "84": "스마트로지스",
    "85": "풀앳홈",
    "86": "삼성전자물류",
    "87": "이투마스(ETOMARS)",
    "88": "큐런택배",
    "89": "두발히어로",
    "90": "위니아딤채",
    "91": "하이브시티",
    "92": "지니고 당일배송",
    "93": "팬스타국제특송(PIEX)",
    "94": "오늘의픽업",
    "95": "큐익스프레스",
    "96": "로지스밸리",
    "97": "에이씨티앤코아물류",
    "99": "롯데택배 해외특송",
    "100": "나은물류",
    "101": "한샘서비스원 택배",
    "102": "배송하기좋은날(SHIPNERGY)",
    "103": "NDEX KOREA",
    "104": "도도플렉스(dodoflex)",
    "105": "BRIDGE LOGIS",
    "106": "허브넷로지스틱스",
    "107": "LG전자(판토스)",
    "108": "MEXGLOBAL",
    "109": "파테크해운항공",
    "110": "부릉",
    "111": "SBGLS",
    "112": "1004홈",
    "113": "썬더히어로",
    "114": "캐나다쉬핑",
    "116": "(주)팀프레시",
    "118": "롯데칠성",
    "119": "핑퐁",
    "120": "발렉스 특수물류",
    "121": "바바바(bababa)",
    "122": "BAIMA EXPRESS",
    "123": "엔티엘피스",
    "124": "LTL",
    "125": "GTS로지스",
    "126": "㈜올타코리아",
    "127": "로지스팟",
    "128": "판월드로지스틱㈜",
    "129": "홈픽 오늘도착",
    "130": "UFO로지스",
    "131": "딜리래빗",
    "132": "지오피",
    "134": "에이치케이홀딩스",
    "135": "HTNS",
    "136": "케이제이티",
    "137": "더바오",
    "138": "라스트마일",
    "139": "오늘회 러쉬",
    "140": "직구문",
    "141": "인터로지스",
    "142": "탱고앤고",
    "143": "투데이",
    "144": "큐브플로우(CUBEFLOW)",
    "999": "직접배송",
}


class DeliveryTrackingRequestFail(Exception):
    ...


async def initiate_tracking_numbers(input):
    data = {
        "callback_url": config.TRX_EXTERNAL_URL + "/delivery-tracking/callback",
        "callback_type": "json",
        "tier": config.DELIVERY_SETTINGS.SMART_DELIVERY_TIER,
        "key": config.DELIVERY_SETTINGS.SMART_DELIVERY_KEY,
        "list": input,
    }
    try:
        async with httpx.AsyncClient() as cl:
            response = await cl.post(
                config.DELIVERY_SETTINGS.SMART_DELIVERY_HOST + "/add_invoice_list", json=data, timeout=2
            )
            response.raise_for_status()  # If not in 200 ~ or 300 ~ range, raise expcetion.
    except Exception:
        raise DeliveryTrackingRequestFail
    else:
        res = response.json()
        return res


async def delivery_tracking_caller(carrier_number, carrier_code):
    """
    examples: https://info.sweettracker.co.kr/api/v1/trackingInfo? \
    t_key=lyokETRIEfNf3xoLGfCzNg&t_code=05&t_invoice=571657817360
    """
    url = (
        f"{config.DELIVERY_SETTINGS.SMART_DELIVERY_TRACKING_STATUS_URL}?"
        f"t_key={config.DELIVERY_SETTINGS.SMART_DELIVERY_API_KEY}&t_code={carrier_code}&t_invoice={carrier_number}"
    )
    try:
        async with httpx.AsyncClient() as cl:
            response = await cl.get(url, timeout=2)
            res = response.json()
            response.raise_for_status()  # If not in 200 ~ or 300 ~ range, raise exception.
    except (httpx.HTTPStatusError, httpx.HTTPError) as e:
        logger.error(e)
        raise DeliveryTrackingRequestFail("Smart Delivery Tracker Connection ERROR")
    tracking_data: dict = dict(
        carrier_name=carrier_code_and_name[carrier_code],
        invoiceNo=res.get("invoiceNo", ""),
        level=res.get("level", 0),
        trackingDetails=res.get("trackingDetail", []),
    )
    return tracking_data
