#!/usr/bin/env python

import asyncio
import copy
import random
import re
import time

import aiohttp
import uvloop

from nettacker.core.lib.base import BaseEngine
from nettacker.core.utils.common import (
    replace_dependent_response,
    reverse_and_regex_condition,
    get_http_header_key,
    get_http_header_value,
)

asyncio.set_event_loop_policy(uvloop.EventLoopPolicy())


async def perform_request_action(action, request_options):
    start_time = time.time()
    async with action(**request_options) as response:
        return {
            "reason": response.reason,
            "url": str(response.url),
            "status_code": str(response.status),
            "content": await response.content.read(),
            "headers": dict(response.headers),
            "responsetime": time.time() - start_time,
        }


async def send_request(request_options, method):
    async with aiohttp.ClientSession() as session:
        action = getattr(session, method, None)
        response = await asyncio.gather(
            *[asyncio.ensure_future(perform_request_action(action, request_options))]
        )
        return response[0]


def response_conditions_matched(sub_step, response):
    if not response:
        return {}
    condition_type = sub_step["response"]["condition_type"]
    conditions = sub_step["response"]["conditions"]
    condition_results = {}
    for condition in conditions:
        if condition in ["reason", "status_code", "content", "url"]:
            regex = re.findall(re.compile(conditions[condition]["regex"]), response[condition])
            reverse = conditions[condition]["reverse"]
            condition_results[condition] = reverse_and_regex_condition(regex, reverse)
        if condition == "headers":
            # convert headers to case insensitive dict
            for key in response["headers"].copy():
                response["headers"][key.lower()] = response["headers"][key]
            condition_results["headers"] = {}
            for header in conditions["headers"]:
                reverse = conditions["headers"][header]["reverse"]
                try:
                    regex = re.findall(
                        re.compile(conditions["headers"][header]["regex"]),
                        response["headers"][header.lower()]
                        if header.lower() in response["headers"]
                        else False,
                    )
                    condition_results["headers"][header] = reverse_and_regex_condition(
                        regex, reverse
                    )
                except TypeError:
                    condition_results["headers"][header] = []
        if condition == "responsetime":
            if len(conditions[condition].split()) == 2 and conditions[condition].split()[0] in [
                "==",
                "!=",
                ">=",
                "<=",
                ">",
                "<",
            ]:
                exec(
                    "condition_results['responsetime'] = response['responsetime'] if ("
                    + "response['responsetime'] {0} float(conditions['responsetime'].split()[-1])".format(
                        conditions["responsetime"].split()[0]
                    )
                    + ") else []"
                )
            else:
                condition_results["responsetime"] = []
    if condition_type.lower() == "or":
        # if one of the values are matched, it will be a string or float object in the array
        # we count False in the array and if it's not all []; then we know one of the conditions
        # is matched.
        if (
            "headers" not in condition_results
            and (
                list(condition_results.values()).count([]) != len(list(condition_results.values()))
            )
        ) or (
            "headers" in condition_results
            and (
                len(list(condition_results.values()))
                + len(list(condition_results["headers"].values()))
                - list(condition_results.values()).count([])
                - list(condition_results["headers"].values()).count([])
                - 1
                != 0
            )
        ):
            if sub_step["response"].get("log", False):
                condition_results["log"] = sub_step["response"]["log"]
                if "response_dependent" in condition_results["log"]:
                    condition_results["log"] = replace_dependent_response(
                        condition_results["log"], condition_results
                    )
            return condition_results
        else:
            return {}
    if condition_type.lower() == "and":
        if [] in condition_results.values() or (
            "headers" in condition_results and [] in condition_results["headers"].values()
        ):
            return {}
        else:
            if sub_step["response"].get("log", False):
                condition_results["log"] = sub_step["response"]["log"]
                if "response_dependent" in condition_results["log"]:
                    condition_results["log"] = replace_dependent_response(
                        condition_results["log"], condition_results
                    )
            return condition_results
    return {}


class HttpEngine(BaseEngine):
    def run(
        self,
        sub_step,
        module_name,
        target,
        scan_id,
        options,
        process_number,
        module_thread_number,
        total_module_thread_number,
        request_number_counter,
        total_number_of_requests,
    ):
        if options["http_header"] is not None:
            for header in options["http_header"]:
                key = get_http_header_key(header).strip()
                value = get_http_header_value(header)
                if value is not None:
                    sub_step["headers"][key] = value.strip()
                else:
                    sub_step["headers"][key] = ""
        backup_method = copy.deepcopy(sub_step["method"])
        backup_response = copy.deepcopy(sub_step["response"])
        backup_iterative_response_match = copy.deepcopy(
            sub_step["response"]["conditions"].get("iterative_response_match", None)
        )
        if options["user_agent"] == "random_user_agent":
            sub_step["headers"]["User-Agent"] = random.choice(options["user_agents"])
        del sub_step["method"]
        if "dependent_on_temp_event" in backup_response:
            temp_event = self.get_dependent_results_from_database(
                target,
                module_name,
                scan_id,
                backup_response["dependent_on_temp_event"],
            )
            sub_step = self.replace_dependent_values(sub_step, temp_event)
        backup_response = copy.deepcopy(sub_step["response"])
        del sub_step["response"]
        for _i in range(options["retries"]):
            try:
                response = asyncio.run(send_request(sub_step, backup_method))
                response["content"] = response["content"].decode(errors="ignore")
                break
            except Exception:
                response = []
        sub_step["method"] = backup_method
        sub_step["response"] = backup_response

        if backup_iterative_response_match is not None:
            backup_iterative_response_match = copy.deepcopy(
                sub_step["response"]["conditions"].get("iterative_response_match")
            )
            del sub_step["response"]["conditions"]["iterative_response_match"]

        sub_step["response"]["conditions_results"] = response_conditions_matched(
            sub_step, response
        )

        if backup_iterative_response_match is not None and (
            sub_step["response"]["conditions_results"]
            or sub_step["response"]["condition_type"] == "or"
        ):
            sub_step["response"]["conditions"][
                "iterative_response_match"
            ] = backup_iterative_response_match
            for key in sub_step["response"]["conditions"]["iterative_response_match"]:
                result = response_conditions_matched(
                    sub_step["response"]["conditions"]["iterative_response_match"][key],
                    response,
                )
                if result:
                    sub_step["response"]["conditions_results"][key] = result

        return self.process_conditions(
            sub_step,
            module_name,
            target,
            scan_id,
            options,
            response,
            process_number,
            module_thread_number,
            total_module_thread_number,
            request_number_counter,
            total_number_of_requests,
        )
