from flask import Flask, jsonify, request
import logging

app = Flask(__name__)

# Setup basic logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

@app.route('/api/resource', methods=['GET'])
def get_resource():
    # Placeholder for Fetching resource
    logger.info('Fetching resource')
    return jsonify({'data': 'Resource data'}), 200

if __name__ == '__main__':
    app.run(debug=True)
