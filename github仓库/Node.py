from BlockchainUtils import BlockChainUtils
from TransactionPool import TransactionPool
from Wallet import Wallet
from Blockchain import Blockchain
from SocketCommunication import SocketCommunication
from NodeAPI import NodeAPI
from Message import Message


class Node():

    def __init__(self, ip, port):
        self.p2p = None
        self.ip = ip
        self.port = port
        self.transactionPool = TransactionPool()
        self.wallet = Wallet()
        self.blockchain = Blockchain()

    def startP2P(self):
        self.p2p = SocketCommunication(self.ip, self.port)
        self.p2p.startSocketCommunication(self)

    def startAPI(self, apiPort):
        self.api = NodeAPI()
        self.api.injectNode(self)
        self.api.start(apiPort)

    def handleTransactions(self, transaction):
        data = transaction.payload()
        signature = transaction.signature
        signerPublicKey = transaction.senderpublickey
        signatureValid = Wallet.signatureValid(
            data, signature, signerPublicKey)
        transactionExists = self.transactionPool.transactionExists(transaction)
        if not transactionExists and signatureValid:
            self.transactionPool.addTransaction(transaction)
            message = Message(
                self.p2p.socketConnector, 'TRANSACTION', transaction)
            encodedMessage = BlockChainUtils.encode(message)
            self.p2p.broadcast(encodedMessage)

    def handleBlock(self, block):
        """校验区块合法性后上链，并向全网广播"""
        lastBlock = self.blockchain.blocks[-1]
        lastBlockHash = BlockChainUtils.hash(lastBlock.payload()).hexdigest()
        lastBlockHashValid = lastBlockHash == block.lastHash
        blockCountValid = lastBlock.blockCount == block.blockCount - 1
        blockSignatureValid = Wallet.signatureValid(
            block.payload(), block.signature, block.forger)
        if lastBlockHashValid and blockCountValid and blockSignatureValid:
            self.blockchain.addBlock(block)
            self.transactionPool.removeFromPool(block.transactions)
            message = Message(
                self.p2p.socketConnector, 'BLOCK', block)
            encodedMessage = BlockChainUtils.encode(message)
            self.p2p.broadcast(encodedMessage)
            return True
        return False

    def createBlockFromTransactionPool(self):
        """将交易池打包成一个新区块（演示出块：本节点钱包签名锻造）"""
        transactions = self.transactionPool.transactions
        if not transactions:
            return None
        lastBlock = self.blockchain.blocks[-1]
        lastHash = BlockChainUtils.hash(lastBlock.payload()).hexdigest()
        blockCount = lastBlock.blockCount + 1
        block = self.wallet.createBlock(transactions, lastHash, blockCount)
        success = self.handleBlock(block)
        if success:
            return block
        return None