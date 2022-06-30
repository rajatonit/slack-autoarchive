#!/usr/bin/env python
"""
This program lets you do archive slack channels which are no longer active.
"""

# standard imports
from datetime import datetime
import os
import sys
import time
import json

# not standard imports
import requests
from config import get_channel_reaper_settings
from utils import get_logger
from dotenv import load_dotenv

load_dotenv()

class ChannelReaper():
    """
    This class can be used to archive slack channels.
    """

    def __init__(self):
        self.settings = get_channel_reaper_settings()
        self.logger = get_logger('channel_reaper', './audit.log')

    def get_whitelist_keywords(self):
        """
        Get all whitelist keywords. If this word is used in the channel
        purpose or topic, this will make the channel exempt from archiving.
        """
        keywords = []
        if os.path.isfile('whitelist.txt'):
            with open('whitelist.txt') as filecontent:
                keywords = filecontent.readlines()

        # remove whitespace characters like `\n` at the end of each line
        keywords = map(lambda x: x.strip(), keywords)
        whitelist_keywords = self.settings.get('whitelist_keywords')
        if whitelist_keywords:
            keywords = keywords + whitelist_keywords.split(',')
        return list(keywords)

    def slack_api_http(self, api_endpoint=None, payload=None, method='GET'):
        """ Helper function to query the slack api and handle errors and rate limit. """
        uri = f'https://slack.com/api/{api_endpoint}'
        header = {'Authorization': f'Bearer {self.settings.get("bot_slack_token")}'}
        try:
            if method == 'POST':
                response = requests.post(uri, headers=header, data=payload)
            else:
                response = requests.get(uri, headers=header, params=payload)

        except requests.exceptions.RequestException as e:
            # TODO: Do something more interesting here?
            raise SystemExit(e)

        if response.status_code  == requests.codes.too_many_requests:
            timeout = int(response.headers['retry-after']) + 3
            self.logger.info(
                f'rate-limited: Trying again in {timeout} seconds.'
            )
            time.sleep(timeout)
            return self.slack_api_http(api_endpoint, payload, method)

        if response.status_code == requests.codes.ok and \
           response.json().get('error', False) == 'not_authed':
            self.logger.error(
                f'Need to setup auth. eg, BOT_SLACK_TOKEN=<secret token> ' \
                f'python slack-autoarchive.py'
            )
            sys.exit(1)

        return response.json()

    def get_all_channels(self):
        """ Get a list of all non-archived channels from slack channels.list. """
        payload = {'exclude_archived': 1}
        api_endpoint = 'conversations.list'

        channels = []
        resp = self.slack_api_http(api_endpoint=api_endpoint,
                                       payload=payload)
        channels.extend(resp['channels'])

        while resp.get("response_metadata"):
            metadata = resp.get("response_metadata")
            if metadata.get('next_cursor'):
                payload['cursor'] = metadata.get('next_cursor')
                resp = self.slack_api_http(api_endpoint=api_endpoint,
                                           payload=payload)
                channels.extend(resp['channels'])
            else:
                break

        all_channels = []
        for channel in channels:
            all_channels.append({
                'id': channel['id'],
                'name': channel['name'],
                'created': channel['created'],
                'num_members': channel['num_members'],
                'is_member': channel['is_member']
            })
        return all_channels

    def get_last_message_timestamp(self, channel_history, too_old_datetime):
        """ Get the last message from a slack channel, and return the time. """
        last_message_datetime = None
        last_bot_message_datetime = too_old_datetime

        if 'messages' not in channel_history:
            return (too_old_datetime, False)  # no messages

        for message in channel_history['messages']:
            if 'subtype' in message and message[
                    'subtype'] in ['channel_leave', 'channel_join']:
                continue
            last_message_datetime = datetime.fromtimestamp(float(
                message['ts']))
            # print(last_message_datetime)
            break
        # for folks with the free plan, sometimes there is no last message,
        # then just set last_message_datetime to epoch
        # if not last_message_datetime:
        #     last_bot_message_datetime = datetime.utcfromtimestamp(0)
        # return bot message time if there was no user message
        if last_message_datetime == None:
            return (too_old_datetime, False)
            
        # if too_old_datetime >= last_bot_message_datetime > too_old_datetime:
        #     return (last_bot_message_datetime, False)
        
        # print(last_message_datetime)
     
        return (last_message_datetime, True)
        

    def is_channel_disused(self, channel, too_old_datetime):
        """ Return True or False depending on if a channel is "active" or not.  """
        num_members = channel['num_members']
        payload = {'inclusive': 0, 'oldest': 0, 'limit': 50}
        api_endpoint = 'conversations.history'

        payload['channel'] = channel['id']
        channel_history = self.slack_api_http(api_endpoint=api_endpoint,
                                              payload=payload)
        # print(channel_history)
        (last_message_datetime, is_user) = self.get_last_message_timestamp(
            channel_history, datetime.fromtimestamp(float(channel['created'])))
        # mark inactive if last message is too old, but don't
        # if there have been bot messages and the channel has
        # at least the minimum number of members
        min_members = self.settings.get('min_members')
        has_min_users = (min_members == 0 or min_members > num_members)
        return last_message_datetime <= too_old_datetime and (not is_user
                                                              or has_min_users) , last_message_datetime

    # If you add channels to the WHITELIST_KEYWORDS constant they will be exempt from archiving.
    def is_channel_whitelisted(self, channel, white_listed_channels):
        """ Return True or False depending on if a channel is exempt from being archived. """
        # self.settings.get('skip_channel_str')
        # if the channel purpose contains the string self.settings.get('skip_channel_str'), we'll skip it.

        info_payload = {'channel': channel['id']}
        channel_info = self.slack_api_http(api_endpoint='conversations.info',
                                           payload=info_payload,
                                           method='GET')
        channel_purpose = channel_info['channel']['purpose']['value']
        channel_topic = channel_info['channel']['topic']['value']
        if self.settings.get(
                'skip_channel_str') in channel_purpose or self.settings.get(
                    'skip_channel_str') in channel_topic:
            return True

        # check the white listed channels (file / env)
        for white_listed_channel in white_listed_channels:
            wl_channel_name = white_listed_channel.strip('#')
            if wl_channel_name in channel['name']:
                return True
        return False

    def send_channel_message(self, channel_id, message):
        """ Send a message to a channel or user. """
        payload = {
            'channel': channel_id,
            'text': message
        }
        api_endpoint = 'chat.postMessage'
        self.slack_api_http(api_endpoint=api_endpoint,
                            payload=payload,
                            method='POST')

    def archive_channel(self, channel):
        """ Archive a channel, and send alert to slack admins. """
        api_endpoint = 'conversations.archive'

        if not self.settings.get('dry_run'):
            self.logger.info(f'Archiving channel #{channel["name"]}')
            payload = {'channel': channel['id']}
            resp = self.slack_api_http(api_endpoint=api_endpoint, \
                                       payload=payload)
            if not resp.get('ok'):
              stdout_message = f'Error archiving #{channel["name"]}: ' \
                               f'{resp["error"]}'
              self.logger.error(stdout_message)
        else:
            self.logger.info(f'THIS IS A DRY RUN. ' \
              f'{channel["name"]} would have been archived.')

    def join_channel(self, channel):
        """ Joins a channel so that the bot can read the last message. """
        # if channel["name"] in ['#testarchive']:
        self.logger.info(f'Adding bot to #{channel["name"]}')
        join_api_endpoint='conversations.join'
        join_payload = {'channel': channel['id']}
        channel_info = self.slack_api_http(api_endpoint=join_api_endpoint, \
                                            payload=join_payload)

        # if not self.settings.get('dry_run'):
        #   self.logger.info(f'Adding bot to #{channel["name"]}')
        #   join_api_endpoint='conversations.join'
        #   join_payload = {'channel': channel['id']}
        #   channel_info = self.slack_api_http(api_endpoint=join_api_endpoint, \
        #                                      payload=join_payload)
        # else:
        #   self.logger.info(
        #     f'THIS IS A DRY RUN. BOT would have joined {channel["name"]}')

    def send_admin_report(self, channels):
        """ Optionally this will message admins with which channels were archived. """
        if self.settings.get('admin_channel'):
            channel_names = ', '.join('#' + channel['name']
                                      for channel in channels)
            admin_msg = f'Archiving {len(channels)} channels: {channel_names}'

            if self.settings.get('dry_run'):
                admin_msg = f'[DRY RUN] {admin_msg}'
            self.send_channel_message(self.settings.get('admin_channel'),
                                      admin_msg)

    def main(self):
        """
        This is the main method that checks all inactive channels and archives them.
        """
        if self.settings.get('dry_run'):
            self.logger.info(
                'THIS IS A DRY RUN. NO CHANNELS ARE ACTUALLY ARCHIVED.')

        whitelist_keywords = self.get_whitelist_keywords()
        archived_channels = []

        self.logger.info(f'Graabing a list of all channels. ' \
              f'This could take a moment depending on the number of channels.')
        # Add bot to all public channels
        too_old_date_time= self.settings.get('too_old_datetime')
        # for channel in self.get_all_channels():
        #     channel_disused , last_message_datetime = self.is_channel_disused(
        #         channel, self.settings.get('too_old_datetime'))
        #     if channel_disused:
        #         self.logger.info(f'Found channel #{channel["name"]}... is < than  {too_old_date_time}. It was last updated {last_message_datetime}')
        #         if not channel['is_member']:
        #             self.logger.info(f'Adding bot in #{channel["name"]}... since it is {channel_disused}')
        #             self.join_channel(channel)

        # Only able to archive channels that the bot is a member of
        for channel in self.get_all_channels():
            channel_disused , last_message_datetime = self.is_channel_disused(
                channel, self.settings.get('too_old_datetime'))
            if channel_disused:
                self.logger.info(f'Found channel #{channel["name"]}... is < than  {too_old_date_time}. It was last updated {last_message_datetime}')
                if not channel['is_member']:
                    self.logger.info(f'Adding bot in #{channel["name"]}... since it is {channel_disused}')
                    self.join_channel(channel)
            if channel['is_member']:
              channel_whitelisted = self.is_channel_whitelisted(
                  channel, whitelist_keywords)
              channel_disused = self.is_channel_disused(
                  channel, self.settings.get('too_old_datetime'))
              if (not channel_whitelisted and channel_disused):
                  archived_channels.append(channel)
                  self.archive_channel(channel)
        self.logger.info("I archived the following channels")
        self.logger.info(archived_channels)
        self.send_admin_report(archived_channels)

if __name__ == '__main__':
    CHANNEL_REAPER = ChannelReaper()
    CHANNEL_REAPER.main()
