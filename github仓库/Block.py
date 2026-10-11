import time
import copy
from MerkleTree import MerkleTree


class Block():

    def __init__(self, transactions, lastHash, forger, blockCount):
        self.transactions = transactions
        self.lastHash = lastHash
        self.forger = forger
        self.blockCount = blockCount
        self.timestamp = time.time()
        self.signature = ''
        self.merkleRoot = self.computeMerkleRoot()

    @staticmethod
    def genesis():
        genesisBlock = Block([], 'genesisHash', 'genesis', 0)
        genesisBlock.timestamp = 0
        genesisBlock.merkleRoot = ''
        return genesisBlock

    def computeMerkleRoot(self):
        """批量哈希：区块内所有交易的 payload 哈希经默克尔树聚合为单一根"""
        tree = MerkleTree.fromTransactions(self.transactions)
        return tree['root']

    def toJson(self):
        data = {}
        data['lastHash'] = self.lastHash
        data['forger'] = self.forger
        data['blockCount'] = self.blockCount
        data['timestamp'] = self.timestamp
        data['signature'] = self.signature
        data['merkleRoot'] = self.merkleRoot
        jsonTransactions = []
        for transaction in self.transactions:
            jsonTransactions.append(transaction.toJson())
        data['transactions'] = jsonTransactions
        return data

    def payload(self):
        jsonRepresentation = copy.deepcopy(self.toJson())
        jsonRepresentation['signature'] = ''
        return jsonRepresentation

    def sign(self, signature):
        self.signature = signature