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
from slack_autoarchive import ChannelReaper

load_dotenv()
cr = ChannelReaper()
number_channels = 50
channel_name_prefix = 'an-interesting-channel'

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
        resp = cr.slack_api_http('conversations.create', payload, 'POST')

        if resp['ok']:
            payload = {'channel': resp['channel']['id']}
            resp_leave = cr.slack_api_http('conversations.leave', payload, 'POST')

            if not resp_leave['ok']:
                print(f'Error removing the bot from #{channel_name}: '\
                      f'{resp_leave.json()["error"]}')
        else:
            print(resp)
