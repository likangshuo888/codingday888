from BlockchainUtils import BlockChainUtils


class MerkleTree:

    @staticmethod
    def hashData(data):
        """对任意数据（交易 payload 或字符串）计算 SHA256 哈希"""
        return BlockChainUtils.hash(data).hexdigest()

    @staticmethod
    def build(leafHashes):
        """
        构建默克尔树，返回完整层级结构。
        - 叶子为交易哈希列表
        - 奇数层自动复制最后一个节点补齐
        - 返回 {root, levels, leaves}
        """
        if not leafHashes:
            return {'root': '', 'levels': [], 'leaves': []}

        leaves = list(leafHashes)
        levels = [leaves]
        current = leaves

        while len(current) > 1:
            nextLevel = []
            for i in range(0, len(current), 2):
                left = current[i]
                right = current[i + 1] if i + 1 < len(current) else current[i]
                parentHash = BlockChainUtils.hash(left + right).hexdigest()
                nextLevel.append(parentHash)
            levels.append(nextLevel)
            current = nextLevel

        return {
            'root': current[0],
            'levels': levels,
            'leaves': leafHashes
        }

    @staticmethod
    def fromTransactions(transactions):
        """从交易列表直接构建默克尔树（叶子 = 交易 payload 哈希）"""
        leafHashes = []
        for transaction in transactions:
            leafHashes.append(MerkleTree.hashData(transaction.payload()))
        return MerkleTree.build(leafHashes)

    @staticmethod
    def verify(root, leaf, proof):
        """
        验证某个叶子是否属于该默克尔树。
        proof: [(siblingHash, isLeft)] 按从叶子到根的路径顺序
        """
        current = leaf
        for sibling, isLeft in proof:
            if isLeft:
                current = BlockChainUtils.hash(sibling + current).hexdigest()
            else:
                current = BlockChainUtils.hash(current + sibling).hexdigest()
        return current == root

    @staticmethod
    def generateProof(leafHashes, targetIndex):
        """
        生成某叶子到根的证明路径。
        返回 [(siblingHash, isLeft)]：isLeft 表示 sibling 在左侧
        """
        if not leafHashes or targetIndex < 0 or targetIndex >= len(leafHashes):
            return None
        proof = []
        current = list(leafHashes)
        index = targetIndex
        while len(current) > 1:
            if index % 2 == 0:
                sibling = current[index + 1] if index + 1 < len(current) else current[index]
                proof.append((sibling, False))
            else:
                sibling = current[index - 1]
                proof.append((sibling, True))
            nextLevel = []
            for i in range(0, len(current), 2):
                left = current[i]
                right = current[i + 1] if i + 1 < len(current) else current[i]
                nextLevel.append(BlockChainUtils.hash(left + right).hexdigest())
            current = nextLevel
            index = index // 2
        return proof
