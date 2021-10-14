#!/usr/bin/env python
"""
Super quick way to create empty channels in a Slack org.
Intended purpose is to try slack-autoarchive in a test org without
worrying about messing up your current channels or inflicting confusion
to your users.

There's a decent chance slack-autoarchive is broken given the last time
the slack-archive was updated or when Slack updated their product.
"""

import json
import os
import requests
import time
from dotenv import load_dotenv

load_dotenv()

number_channels = 50
channel_name_prefix = 'an-interesting-channel'

def slack_api(api_endpoint, payload):
    uri = f'https://slack.com/api/{api_endpoint}'
    header = {'Authorization': f'Bearer {os.environ.get("BOT_SLACK_TOKEN")}'}

    try:
        resp = requests.post(uri, headers=header, data=payload)
    except requests.exceptions.RequestException as e:
        print('Something unexpected happened...')
        SystemExit(e)

    if resp.status_code == requests.codes.too_many_requests:
        timeout = int(resp.headers['retry-after']) + 3
        print(f'rate-limited: Trying again in {timeout} seconds.')
        time.sleep(timeout)
        return slack_api(api_endpoint, payload)
    else:
        return resp


if __name__ == '__main__':
    if os.environ.get('BOT_SLACK_TOKEN', False) == False:
      print('Need to set BOT_SLACK_TOKEN before running this program.\n\n' \
            'Either set it in .env or run this script as:\n' \
            'BOT_SLACK_TOKEN=<secret token> python create_test_channels.py')
      exit(1)
      
    for x in range(number_channels):
        channel_name = f'{channel_name_prefix}-{x}'
        payload = {'name': channel_name}
        print(f'Creating channel: {channel_name}')
        resp = slack_api('conversations.create', payload)
        response = resp.json()

        if response['ok']:
            payload = {'channel': response['channel']['id']}
            resp_leave = slack_api('conversations.leave', payload)

            if not resp_leave.json()['ok']:
                print(f'Error removing the bot from #{channel_name}: '\
                      f'{resp_leave.json()["error"]}')
        else:
            print(response)
            print(response['error'])
