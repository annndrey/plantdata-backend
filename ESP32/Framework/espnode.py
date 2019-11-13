import requests

class ESPNode:
	def __init__(self, node_ip):
		self.ip = node_ip

	def get_data(self):
		response = requests.get('{}/send_data'.format(self.ip))
		if response.status_code == 200:
			return response.body
		elif response.status_code == 404:
			return 'nan'