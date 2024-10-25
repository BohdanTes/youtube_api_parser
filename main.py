import requests
import json
import sys
import argparse
import time

"""
Youtube api v3 docs: https://developers.google.com/youtube/v3/getting-started
Quota calculator: https://developers.google.com/youtube/v3/determine_quota_cost
"Projects that enable the YouTube Data API have a default quota allocation of 10,000 units per day."

Firstly we need to get channel playlist id by channel id using "channels" api request (costs 1 quota unit).
Since the maximum page size that api can send is 50 items (videos) we need to make
a chain of requests and use the "nextPageToken" field to change the "pageToken" parameter
in the url for each request ("playlistItems" api request costs 1 quota unit per request).
"""

api_request_allow = True
default_out_file_path = "ytb_channel_data"
default_max_results = 50


def stubborn_request(url, sec_bet_req=2):

    response = None
    while response is None:
        try:
            response = requests.get(url)
        except requests.exceptions.HTTPError:
            print("Http error... Retry")
            time.sleep(sec_bet_req)
        except requests.exceptions.ConnectionError:
            print("Connection error... Retry")
            time.sleep(sec_bet_req)
        except requests.exceptions.Timeout:
            print("Timeout error... Retry")
            time.sleep(sec_bet_req)
        except requests.exceptions.RequestException:
            print("Request error... Retry")
            time.sleep(sec_bet_req)
    return response


def api_get_request(url, exit_if_not=False):
    global api_request_allow

    if api_request_allow:
        response = stubborn_request(url)
        if response.status_code != 200:
            api_request_allow = False
        else:
            return response

    if not api_request_allow:
        print("\nApi response error!\n")
        if exit_if_not:
            sys.exit("exit")
        return False


def get_channel_id(channel_url):
    try:
        from bs4 import BeautifulSoup
        response = stubborn_request(channel_url).text
        bs = BeautifulSoup(response, 'html.parser')
        # channel_id = bs.find(itemprop="channelId").get("content")
        channel_id = bs.find("link", {"rel": "canonical"})['href'].split('/')[-1]
        return channel_id
    except:
        sys.exit("error: can not parse html page to find channel id")


def fetch_channel_playlist_id(channel_url, max_results, api_key):

    channel_id = get_channel_id(channel_url)

    url = f"https://youtube.googleapis.com/youtube/v3/channels?part=contentDetails&id={channel_id}&maxResults={max_results}&key={api_key}"
    channel_playlist_id_response_json = api_get_request(url, exit_if_not=True).json()
    playlist_id = channel_playlist_id_response_json["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    return playlist_id


def fetch_channel_data(playlist_id, max_results, api_key, get_play_list_url):

    url = f"{get_play_list_url}key={api_key}&playlistId={playlist_id}&part=snippet,id,contentDetails&maxResults={max_results}"
    response_json = api_get_request(url, exit_if_not=True).json()

    channel_title = None
    if not len(response_json["items"]) == 0:
        channel_title = response_json["items"][0]["snippet"]["channelTitle"]
    videos_number = response_json["pageInfo"]["totalResults"]

    return channel_title, videos_number


def get_videos_list(playlist_id, max_results, api_key, get_play_list_url, get_videos_url):

    page_token = ""
    run = True
    videos_list = []
    total_counter = 0

    next_token_url_part = "&pageToken="
    youtube_link = "https://www.youtube.com/watch?v="

    while run:
        """ 
        Sometimes when you make too many requests server may freeze your current request.
        You just need to wait a few seconds (5 - 15) and parsing will continue.
        """

        # print("\nRequest details...")
        url = get_play_list_url + f"key={api_key}&playlistId={playlist_id}&part=snippet,id,contentDetails&maxResults={max_results}{page_token}"

        response = api_get_request(url)
        if response == False:
            return videos_list

        json_response = response.json()

        title_buffer = []
        description_buffer = []
        video_id_buffer = []
        publish_time_buffer = []

        # Parsing json
        # print("Parsing details...")
        for item in json_response["items"]:
            if item["kind"] == "youtube#playlistItem":

                title = item["snippet"]["title"] if "title" in item["snippet"] else None
                description = item["snippet"]["description"] if "description" in item["snippet"] else None
                video_id = item["contentDetails"]["videoId"] if "videoId" in item["contentDetails"] else None
                publish_time = item["snippet"]["publishedAt"].replace('T', ' ').replace('Z', '') if "publishedAt" in item["snippet"] else None

                title_buffer.append(title)
                description_buffer.append(description)
                video_id_buffer.append(video_id)
                publish_time_buffer.append(publish_time)

                # Logging
                total_counter += 1

        # Sending a request for videos statistics data (likes, views, comments_number)
        # print("Request statistics...")
        videos_id_str = ",".join(video_id_buffer)
        videos_statistics_url = f"{get_videos_url}key={api_key}&maxResults={max_results}&part=statistics&id={videos_id_str}"

        videos_statistics_response = api_get_request(videos_statistics_url)
        if videos_statistics_response == False:
            return videos_list

        videos_statistics_json = videos_statistics_response.json()

        # print("Parsing statistics...")
        for i, video in enumerate(videos_statistics_json["items"]):

            views = video["statistics"]["viewCount"] if "viewCount" in video["statistics"] else None
            likes = video["statistics"]["likeCount"] if "likeCount" in video["statistics"] else None
            comments_number = video["statistics"]["commentCount"] if "commentCount" in video["statistics"] else None

            # Json style list formation
            videos_list.extend([{

                "title": title_buffer[i],
                "link": f"{youtube_link}{video_id_buffer[i]}",
                "publish_time": publish_time_buffer[i],
                "views": views,
                "likes": likes,
                "comments_number": comments_number,
                "description": description_buffer[i],

            }])

        print(f"Parsed {total_counter} videos")

        # If the next json page doesn't have "nextPageToken" parameter -> parsed all videos on the channel -> break
        # Else change token in the url and continue making requests to the api
        if "nextPageToken" in json_response:
            page_token = next_token_url_part + json_response["nextPageToken"]
        else:
            run = False

    return videos_list


def correct_args(args):
    global default_max_results

    warn_m = "warning: {} argument changed to default: {}"

    # Arguments validation and correction
    if int(args.maxr) <= 0 or int(args.maxr) > default_max_results:
        args.maxr = default_max_results
        print(warn_m.format("-maxr", default_max_results))

    return args


def get_args():
    global default_out_file_path, default_max_results

    parser = argparse.ArgumentParser()
    parser.add_argument("-url", help="Channel link")
    parser.add_argument("-key", help="Your youtube api key")
    parser.add_argument("-out", help=f"Path to the out json file, default: '{default_out_file_path}.json'",
                        default=default_out_file_path)
    parser.add_argument("-maxr", help=f"Max results per request, default: {default_max_results}, it's apis maximum",
                        default=default_max_results)
    args = parser.parse_args(sys.argv[1:])

    print("\nArguments validation...")
    return correct_args(args)


def validate_args(args):

    error_m = ""
    url_resp = stubborn_request(args.url)
    api_resp = stubborn_request(
            f"https://youtube.googleapis.com/youtube/v3/channels?part=contentDetails&id=UCK8sQmJBp8GCxrOtXWBpyEA&maxResults=50&key={args.key}")

    # Http errors validation
    if url_resp.status_code == 404:
        error_m += f"Error: youtube channel '{args.url}' do not exists!\n"
    if api_resp.status_code == 400:
        error_m += f"Error: api key '{args.key}' not valid!\n"

    if url_resp.status_code != 404 and url_resp.status_code != 200:
        error_m += f"Error: url response error!\n"
    if api_resp.status_code != 400 and api_resp.status_code != 200:
        error_m += f"Error: api response error!\n"

    # Arguments errors validation
    os_can_save = lambda file_name: len([True for s in '\/:*?"<>|' if s in file_name]) == 0
    if not os_can_save(args.out):
        error_m += 'Error: file name can not contain \/:*?"<>| symbols!\n'

    return error_m


def main():

    args = get_args()
    validation_error = validate_args(args)
    if validation_error != "":
        print(validation_error)
        return

    # Your values
    channel_url = args.url
    json_file_name = args.out
    max_results = int(args.maxr)  # youtube api v3 can return from 0 to 50 results per 1 page
    api_key = args.key

    # Api url to get playlist items (videos)
    get_playlist_url = "https://www.googleapis.com/youtube/v3/playlistItems?"

    # Api url to get videos by id
    get_videos_url = "https://www.googleapis.com/youtube/v3/videos?"

    print("\nFetching channel id & playlist id...")
    # Fetching channel playlist id
    playlist_id = fetch_channel_playlist_id(channel_url, max_results, api_key)

    print("Fetching channel data...")
    # Fetching channel data (title and number of videos)
    channel_title, videos_number = fetch_channel_data(playlist_id, max_results, api_key, get_playlist_url)

    # Fetch all videos from channel (channel playlist)
    videos_list = get_videos_list(playlist_id, max_results, api_key, get_playlist_url, get_videos_url)

    channel_data_json = {
        "channel_title": channel_title,
        "videos_number": videos_number,
        "videos": videos_list
    }

    # Saving json to the file
    print("\nSaving json file...")
    with open(f"{json_file_name}.json", "w", encoding="utf-8") as file:
        json.dump(channel_data_json, file, indent=4, ensure_ascii=False)


if __name__ == "__main__":
    main()
