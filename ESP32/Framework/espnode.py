import requests
import logging
import json

class ESPNode:
	def __init__(self, node_ip):
		self.ip = node_ip

	def get_data(self):
		try:
			response = requests.get('http://{}/send_data'.format(self.ip))
			node_data = response.text
			node_data = node_data.replace("'", '"')
			node_data = node_data.replace("nan", "-1")
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
		data = node.get_data()
		print(data)
