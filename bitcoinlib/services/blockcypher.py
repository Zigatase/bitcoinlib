# -*- coding: utf-8 -*-
#
#    BitcoinLib - Python Cryptocurrency Library
#    BlockCypher client
#    © 2017-2019 July - 1200 Web Development <http://1200wd.com/>
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

import logging
from datetime import datetime
from bitcoinlib.main import MAX_TRANSACTIONS
from bitcoinlib.services.baseclient import BaseClient, ClientError
from bitcoinlib.transactions import Transaction
from bitcoinlib.encoding import to_hexstring

PROVIDERNAME = 'blockcypher'

_logger = logging.getLogger(__name__)


class BlockCypher(BaseClient):

    def __init__(self, network, base_url, denominator, *args):
        super(self.__class__, self).__init__(network, PROVIDERNAME, base_url, denominator, *args)

    def compose_request(self, function, data, parameter='', variables=None, method='get'):
        url_path = function + '/' + data
        if parameter:
            url_path += '/' + parameter
        if variables is None:
            variables = {}
        if self.api_key:
            variables.update({'token': self.api_key})
        return self.request(url_path, variables, method)

    def getbalance(self, addresslist):
        addresslist = self._addresslist_convert(addresslist)
        addresses = ';'.join([a.address for a in addresslist])
        res = self.compose_request('addrs', addresses, 'balance')
        balance = 0.0
        if not isinstance(res, list):
            res = [res]
        for rec in res:
            balance += float(rec['final_balance'])
        return int(balance * self.units)

    def getutxos(self, addresslist, after_txid='', max_txs=MAX_TRANSACTIONS):
        addresslist = self._addresslist_convert(addresslist)
        utxos = self._address_transactions(addresslist, unspent_only=True, after_txid=after_txid)
        return utxos[:max_txs]

    def _address_transactions(self, addresslist, unspent_only=False, after_txid=''):
        addresses = ';'.join([a.address for a in addresslist])
        res = self.compose_request('addrs', addresses, variables={'unspentOnly': int(unspent_only), 'limit': 2000})
        transactions = []
        if not isinstance(res, list):
            res = [res]
        for a in res:
            address = [x.address_orig for x in addresslist if x.address == a['address']][0]
            if 'txrefs' not in a:
                continue
            if len(a['txrefs']) > 500:
                _logger.warning("BlockCypher: Large number of transactions for address %s, "
                                "Transaction list may be incomplete" % address)
            for tx in a['txrefs']:
                if tx['tx_hash'] == after_txid:
                    break
                transactions.append({
                    'address': address,
                    'tx_hash': tx['tx_hash'],
                    'confirmations': tx['confirmations'],
                    'output_n': tx['tx_output_n'],
                    'index': 0,
                    'value': int(round(tx['value'] * self.units, 0)),
                    'script': '',
                })
        return transactions[::-1]

    def gettransactions(self, addresslist, after_txid='', max_txs=MAX_TRANSACTIONS):
        txs = []
        txids = []
        addresslist = self._addresslist_convert(addresslist)
        for address in addresslist:
            res = self.compose_request('addrs', address.address,
                                       variables={'unspentOnly': 0, 'limit': 2000})
            if not isinstance(res, list):
                res = [res]
            for a in res:
                address = [x.address_orig for x in addresslist if x.address == a['address']][0]
                if 'txrefs' not in a:
                    continue
                txids = []
                for t in a['txrefs'][::-1]:
                    if t['tx_hash'] not in txids:
                        txids.append(t['tx_hash'])
                    if t['tx_hash'] == after_txid:
                        txids = []
                if len(txids) > 500:
                    _logger.warning("BlockCypher: Large number of transactions for address %s, "
                                    "Transaction list may be incomplete" % address)
                for txid in txids[:max_txs]:
                    t = self.gettransaction(txid)
                    txs.append(t)
        return txs

    def gettransaction(self, tx_id):
        tx = self.compose_request('txs', tx_id, variables={'includeHex': 'true'})
        t = Transaction.import_raw(tx['hex'], network=self.network)
        t.hash = tx_id
        if tx['confirmations']:
            t.status = 'confirmed'
        else:
            t.status = 'unconfirmed'
        t.date = datetime.strptime(tx['confirmed'][:19], "%Y-%m-%dT%H:%M:%S")
        t.confirmations = tx['confirmations']
        t.block_height = tx['block_height']
        t.block_hash = tx['block_hash']
        t.fee = tx['fees']
        t.rawtx = tx['hex']
        t.size = tx['size']
        t.network = self.network
        t.input_total = 0
        if t.coinbase:
            t.input_total = t.output_total
        if len(t.inputs) != len(tx['inputs']):
            raise ClientError("Invalid number of inputs provided. Raw tx: %d, blockcypher: %d" %
                              (len(t.inputs), len(tx['inputs'])))
        for n, i in enumerate(t.inputs):
            if not t.coinbase and not (tx['inputs'][n]['output_index'] == i.output_n_int and
                        tx['inputs'][n]['prev_hash'] == to_hexstring(i.prev_hash)):
                raise ClientError("Transaction inputs do not match raw transaction")
            if 'output_value' in tx['inputs'][n]:
                i.value = tx['inputs'][n]['output_value']
                t.input_total += i.value
        if len(t.outputs) != len(tx['outputs']):
            raise ClientError("Invalid number of outputs provided. Raw tx: %d, blockcypher: %d" %
                              (len(t.outputs), len(tx['outputs'])))
        for n, o in enumerate(t.outputs):
            if 'spent_by' in tx['outputs'][n]:
                o.spent = True
        t.raw_hex()
        return t

    def getrawtransaction(self, tx_id):
        return self.compose_request('txs', tx_id, variables={'includeHex': 'true'})['hex']

    def sendrawtransaction(self, rawtx):
        res = self.compose_request('txs', 'push', variables={'tx': rawtx}, method='post')
        return {
            'txid': res['tx']['hash'],
            'response_dict': res
        }

    def estimatefee(self, blocks):
        res = self.compose_request('', '')
        if blocks <= 10:
            return res['medium_fee_per_kb']
        else:
            return res['low_fee_per_kb']

    def block_count(self):
        return self.compose_request('', '')['height']
