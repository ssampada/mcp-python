import requests

class ServiceNowClient:
    def __init__(self, instance_url, username, password):
        self.instance_url = instance_url
        self.username = username
        self.password = password

    def get_data(self):
        # Sample method to get data from ServiceNow
        response = requests.get(f'{self.instance_url}/api/resource')
        return response.json()
