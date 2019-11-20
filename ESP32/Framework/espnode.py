import requests
import logging
import json

ATTEMPTS_LIMIT = 5  # Node availability check attempts limit


class ESPNode:
    def __init__(self, node_ip):
        self.ip = node_ip

    def available(self, attempt=1):
        '''This method checks node availabilaty by making a GET request to node's /info page. 
        Return 1 if node is available. Return 0 if node is not available after few attemptes (amount of attempts are limited by ATTEMPTS_LIMIT variable, 5 by default).
        It is expected to be used as check before any other requests '''

        logging.debug(
            'Check node {}. Attempt number {}'.format(self.ip, attempt))
        try:
            response = requests.get('http://{}/info'.format(self.ip))
        except Exception as e:
            logging.debug('Connection failed with error: {}'.format(repr(e)))
            if attempt <= ATTEMPTS_LIMIT:
                attempt += 1
                return self.available(attempt)
            else:
                logging.debug(
                    'Attempt limit has been reached. Node {} is not available'.format(self.ip))
                return 0
        else:
            logging.debug('Node {} is available'.format(self.ip))
            return 1

    def get_data(self):
        try:
            response = requests.get('http://{}/sensor_data'.format(self.ip))
            node_data = response.text
            #node_data = node_data.replace("'", '"')
            node_data = node_data.replace("null", "-1") #Why are we doing this? @Dan has no idea
            logging.debug(node_data)
            node_data = json.loads(node_data)
            logging.debug("data read from {}".format(self.ip))
        except json.JSONDecodeError as e:
            logging.debug('json next try {}'.format(repr(e)))
            return self.get_data()
        except Exception as e:
            logging.debug('Connection failed with error: {}'.format(repr(e)))
            return self.get_data()
        else:
            logging.debug('json read')
            return node_data


if __name__ == '__main__':
    logging.basicConfig(filename='espnode.log',
                        filemode='w',
                        format='%(asctime)s,%(msecs)d %(name)s %(levelname)s %(message)s',
                        datefmt='%H:%M:%S',
                        level=logging.DEBUG)

    print('Enter node addres: ')
    ip = input()
    node = ESPNode(ip)
    for i in range(50):
        if node.available():
            data = node.get_data()
            print(data)
        else:
            print(-1)
