import os
import time
from flask_classful import FlaskView, route
from flask import Flask, jsonify, request, Response
from BlockchainUtils import BlockChainUtils
from MerkleTree import MerkleTree

node = None


class NodeAPI(FlaskView):

    studentWallets = {}   # studentId -> {'name':..., 'wallet': Wallet()}
    fundStatus = {}       # applyId -> 'pending'/'approved'/'rejected'

    def __init__(self):
        self.app = Flask(__name__)

    def start(self, apiPort):
        NodeAPI.register(self.app, route_base='/')
        self.app.run(host='localhost', port=apiPort, threaded=True)

    def injectNode(self, injectedNode):
        global node
        node = injectedNode

    # ================= 页面 =================

    @staticmethod
    def _page(name):
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)), name)
        if os.path.exists(path):
            with open(path, 'r', encoding='utf-8') as f:
                return Response(f.read(), mimetype='text/html')
        return name + ' not found', 404

    @route('/', methods=['GET'])
    def dashboard(self):
        """平台管控后台（只供平台方查看）"""
        return NodeAPI._page('dashboard.html')

    @route('/app', methods=['GET'])
    def studentApp(self):
        """学生端前台"""
        return NodeAPI._page('student.html')

    @route('/info', methods=['GET'])
    def info(self):
        return 'This Is A Communication Interface To A Nodes Blockchain', 200

    # ================= 基础链接口 =================

    @route('/blockchain', methods=['GET'])
    def blockchain(self):
        return node.blockchain.toJson(), 200

    @route('transactionPool', methods=['GET'])
    def transactionPool(self):
        transactions = {}
        for ctr, transaction in enumerate(node.transactionPool.transactions):
            transactions[ctr] = transaction.toJson()
        return jsonify(transactions), 200

    @route('transaction', methods=['POST'])
    def transaction(self):
        values = request.get_json()
        if not 'transaction' in values:
            return 'Missing Transaction Value', 400
        transaction = BlockChainUtils.decode(values['transaction'])
        node.handleTransactions(transaction)
        response = {'message': 'Received transaction'}
        return jsonify(response), 201

    @route('/api/chain', methods=['GET'])
    def apiChain(self):
        return jsonify(node.blockchain.toJson()), 200

    @route('/api/pool', methods=['GET'])
    def apiPool(self):
        transactions = []
        for transaction in node.transactionPool.transactions:
            data = transaction.toJson()
            data['hash'] = MerkleTree.hashData(transaction.payload())
            transactions.append(data)
        return jsonify(transactions), 200

    @route('/api/peers', methods=['GET'])
    def apiPeers(self):
        peers = []
        p2p = getattr(node, 'p2p', None)
        if p2p is not None and hasattr(p2p, 'peers'):
            for peer in p2p.peers:
                peers.append({'ip': peer.ip, 'port': peer.port})
        return jsonify(peers), 200

    @route('/api/forge', methods=['POST'])
    def apiForge(self):
        """将行为池打包成新区块（含默克尔根批量哈希）"""
        block = node.createBlockFromTransactionPool()
        if block is None:
            return jsonify({'error': '行为池为空，无法出块'}), 400
        return jsonify(block.toJson()), 201

    @route('/api/issue', methods=['POST'])
    def apiIssue(self):
        from Wallet import Wallet
        values = request.get_json(silent=True) or {}
        try:
            amount = int(values.get('amount', 10))
        except (TypeError, ValueError):
            return jsonify({'error': 'amount 必须是整数'}), 400
        if amount <= 0:
            return jsonify({'error': 'amount 必须大于 0'}), 400
        exchange = node.wallet
        receiver = Wallet()
        transaction = exchange.createTransaction(
            receiver.publicKeyString(), amount, 'EXCHANGE')
        node.handleTransactions(transaction)
        return jsonify(transaction.toJson()), 201

    @route('/api/merkle/<int:blockIndex>', methods=['GET'])
    def apiMerkle(self, blockIndex):
        blocks = node.blockchain.blocks
        if blockIndex < 0 or blockIndex >= len(blocks):
            return jsonify({'error': '区块索引越界'}), 404
        block = blocks[blockIndex]
        transactions = block.transactions
        leafHashes = [MerkleTree.hashData(t.payload()) for t in transactions]
        tree = MerkleTree.build(leafHashes)
        payload = {
            'blockIndex': blockIndex,
            'merkleRoot': block.merkleRoot,
            'leaves': [],
            'levels': tree['levels']
        }
        for i, transaction in enumerate(transactions):
            payload['leaves'].append({
                'index': i,
                'txId': transaction.id,
                'hash': leafHashes[i]
            })
        return jsonify(payload), 200

    @route('/api/merkleProof/<int:blockIndex>/<int:txIndex>', methods=['GET'])
    def apiMerkleProof(self, blockIndex, txIndex):
        blocks = node.blockchain.blocks
        if blockIndex < 0 or blockIndex >= len(blocks):
            return jsonify({'error': '区块索引越界'}), 404
        block = blocks[blockIndex]
        leafHashes = [MerkleTree.hashData(t.payload()) for t in block.transactions]
        proof = MerkleTree.generateProof(leafHashes, txIndex)
        if proof is None:
            return jsonify({'error': '交易索引越界'}), 400
        root = block.merkleRoot
        verified = MerkleTree.verify(root, leafHashes[txIndex], proof)
        return jsonify({
            'blockIndex': blockIndex,
            'txIndex': txIndex,
            'root': root,
            'proof': [{'sibling': s, 'isLeft': l} for s, l in proof],
            'verified': verified
        }), 200

    # ================= 通用工具 =================

    @staticmethod
    def _allTransactions():
        """汇总链上 + 池中的全部交易"""
        txs = []
        for block in node.blockchain.blocks:
            for tx in block.transactions:
                txs.append({'tx': tx, 'onchain': True})
        for tx in node.transactionPool.transactions:
            txs.append({'tx': tx, 'onchain': False})
        return txs

    @staticmethod
    def _studentWallet(studentId):
        if studentId not in NodeAPI.studentWallets:
            return None
        return NodeAPI.studentWallets[studentId]['wallet']

    @staticmethod
    def _studentReputation(studentId):
        """诚信度：信誉分 = 行为加权总和；等级 = 青铜/白银/黄金"""
        total = 0
        hours = 0.0
        count = 0
        for item in NodeAPI._allTransactions():
            tx = item['tx']
            t = tx.type
            if t in ('VOLUNTEER', 'VOL_JOIN') and tx.extra.get('studentId') == studentId:
                total += int(tx.amount)
                hours += tx.amount
                count += 1
            elif t in ('CLUB', 'FUND_GRANT') and tx.extra.get('studentId') == studentId:
                total += 10
                count += 1
            elif t == 'COMPETITION' and tx.extra.get('studentId') == studentId:
                total += 20
                count += 1
            elif t in ('BOOK', 'ITEM', 'VOL_TASK') and tx.extra.get('studentId') == studentId:
                total += 5
                count += 1
            elif t == 'BUY':
                if tx.extra.get('buyer') == studentId:
                    total += 5
                    count += 1
                if tx.extra.get('seller') == studentId:
                    total += 15
                    count += 1
        level = '黄金' if total >= 100 else ('白银' if total >= 50 else '青铜')
        return {'reputation': total, 'hours': round(hours, 1), 'count': count, 'level': level}

    @staticmethod
    def _findItem(itemId):
        for item in NodeAPI._allTransactions():
            tx = item['tx']
            if tx.type in ('BOOK', 'ITEM') and tx.id == itemId:
                return NodeAPI._itemInfo(tx)
        return None

    @staticmethod
    def _itemInfo(tx):
        """物品/书籍交易 → 市集条目（附成交状态与卖家诚信）"""
        sold = False
        buyer = None
        for item in NodeAPI._allTransactions():
            t2 = item['tx']
            if t2.type == 'BUY' and t2.extra.get('itemId') == tx.id:
                sold = True
                buyer = t2.extra.get('buyer', '')
                break
        seller = tx.extra.get('studentId', '')
        rep = NodeAPI._studentReputation(seller) if seller else {'reputation': 0, 'level': '青铜'}
        return {
            'txId': tx.id,
            'type': tx.type,
            'category': tx.extra.get('category', 'book'),
            'title': tx.extra.get('title', ''),
            'price': tx.extra.get('price', tx.amount),
            'desc': tx.extra.get('desc', ''),
            'seller': seller,
            'sellerReputation': rep['reputation'],
            'sellerLevel': rep['level'],
            'sold': sold,
            'buyer': buyer,
            'time': tx.timestamp
        }

    @staticmethod
    def _taskInfo(tx):
        """志愿任务 → 任务条目（附接单状态与发布者诚信）"""
        joined = False
        joiners = []
        for item in NodeAPI._allTransactions():
            t2 = item['tx']
            if t2.type == 'VOL_JOIN' and t2.extra.get('taskId') == tx.id:
                joined = True
                joiners.append(t2.extra.get('studentId', ''))
        publisher = tx.extra.get('studentId', '')
        rep = NodeAPI._studentReputation(publisher) if publisher else {'reputation': 0, 'level': '青铜'}
        return {
            'txId': tx.id,
            'title': tx.extra.get('title', ''),
            'hours': tx.extra.get('hours', tx.amount),
            'desc': tx.extra.get('desc', ''),
            'publisher': publisher,
            'publisherReputation': rep['reputation'],
            'publisherLevel': rep['level'],
            'joined': joined,
            'joiners': joiners,
            'time': tx.timestamp
        }

    @staticmethod
    def _fundInfo(tx):
        applyId = tx.id
        status = NodeAPI.fundStatus.get(applyId, tx.extra.get('status', 'pending'))
        return {
            'applyId': applyId,
            'studentId': tx.extra.get('studentId', ''),
            'reason': tx.extra.get('reason', ''),
            'amount': tx.extra.get('amount', tx.amount),
            'status': status,
            'time': tx.timestamp,
            'onchain': True
        }

    # ================= 学生端：身份 =================

    @route('/api/student/register', methods=['POST'])
    def studentRegister(self):
        values = request.get_json(silent=True) or {}
        studentId = str(values.get('studentId', '')).strip()
        name = str(values.get('name', '')).strip() or studentId
        if not studentId:
            return jsonify({'error': '请填写学号'}), 400
        from Wallet import Wallet
        if studentId not in NodeAPI.studentWallets:
            NodeAPI.studentWallets[studentId] = {
                'name': name, 'wallet': Wallet(), 'created': time.time()
            }
        wallet = NodeAPI.studentWallets[studentId]['wallet']
        return jsonify({
            'studentId': studentId,
            'name': NodeAPI.studentWallets[studentId]['name'],
            'publicKey': wallet.publicKeyString(),
            'chainId': wallet.publicKeyString().split('\n')[1][:16] + '...'
        }), 200

    # ================= 学生端：闲置市集（书 + 物品） =================

    @route('/api/student/book', methods=['POST'])
    def studentBook(self):
        return NodeAPI._publishItem('BOOK')

    @route('/api/student/item', methods=['POST'])
    def studentItem(self):
        return NodeAPI._publishItem('ITEM')

    @staticmethod
    def _publishItem(txType):
        values = request.get_json(silent=True) or {}
        studentId = str(values.get('studentId', '')).strip()
        wallet = NodeAPI._studentWallet(studentId)
        if wallet is None:
            return jsonify({'error': '请先注册学生身份'}), 400
        title = str(values.get('title', '')).strip()
        desc = str(values.get('desc', '')).strip()
        category = str(values.get('category', 'book')).strip()
        try:
            price = int(values.get('price', 0))
        except (TypeError, ValueError):
            return jsonify({'error': '价格必须是整数'}), 400
        if not title:
            return jsonify({'error': '请填写名称'}), 400
        if price <= 0:
            return jsonify({'error': '价格必须大于 0'}), 400
        tx = wallet.createTransaction(
            node.wallet.publicKeyString(), price, txType,
            {'title': title, 'price': price, 'desc': desc,
             'studentId': studentId, 'category': category})
        node.handleTransactions(tx)
        return jsonify(tx.toJson()), 201

    @route('/api/student/buy', methods=['POST'])
    def studentBuy(self):
        values = request.get_json(silent=True) or {}
        studentId = str(values.get('studentId', '')).strip()
        wallet = NodeAPI._studentWallet(studentId)
        if wallet is None:
            return jsonify({'error': '请先注册学生身份'}), 400
        itemId = str(values.get('itemId', '')).strip()
        if not itemId:
            return jsonify({'error': '缺少物品 ID'}), 400
        item = NodeAPI._findItem(itemId)
        if item is None:
            return jsonify({'error': '物品不存在'}), 404
        if item['sold']:
            return jsonify({'error': '该物品已被购买'}), 400
        if item['seller'] == studentId:
            return jsonify({'error': '不能购买自己发布的物品'}), 400
        tx = wallet.createTransaction(
            item['sellerPub'] if 'sellerPub' in item else node.wallet.publicKeyString(),
            item['price'], 'BUY',
            {'itemId': itemId, 'title': item['title'], 'price': item['price'],
             'buyer': studentId, 'seller': item['seller'],
             'itemType': item['type'], 'category': item['category']})
        node.handleTransactions(tx)
        return jsonify(tx.toJson()), 201

    @route('/api/student/items', methods=['GET'])
    def studentItems(self):
        """闲置市集：全部 BOOK/ITEM（含成交状态与卖家诚信）"""
        items = []
        seen = set()
        for item in NodeAPI._allTransactions():
            tx = item['tx']
            if tx.type in ('BOOK', 'ITEM') and tx.id not in seen:
                seen.add(tx.id)
                info = NodeAPI._itemInfo(tx)
                info['onchain'] = item['onchain']
                items.append(info)
        items.sort(key=lambda b: b['time'], reverse=True)
        return jsonify(items), 200

    # ================= 学生端：志愿服务（打卡 + 任务市场接单） =================

    @route('/api/student/volunteer', methods=['POST'])
    def studentVolunteer(self):
        values = request.get_json(silent=True) or {}
        studentId = str(values.get('studentId', '')).strip()
        wallet = NodeAPI._studentWallet(studentId)
        if wallet is None:
            return jsonify({'error': '请先注册学生身份'}), 400
        project = str(values.get('project', '')).strip()
        try:
            hours = float(values.get('hours', 0))
        except (TypeError, ValueError):
            return jsonify({'error': '时长必须是数字'}), 400
        if not project:
            return jsonify({'error': '请填写服务项目'}), 400
        if hours <= 0:
            return jsonify({'error': '时长必须大于 0'}), 400
        tx = wallet.createTransaction(
            node.wallet.publicKeyString(), hours, 'VOLUNTEER',
            {'project': project, 'hours': hours, 'studentId': studentId})
        node.handleTransactions(tx)
        return jsonify(tx.toJson()), 201

    @route('/api/student/volTask', methods=['POST'])
    def studentVolTask(self):
        """发布志愿服务任务（供其他学生接单）"""
        values = request.get_json(silent=True) or {}
        studentId = str(values.get('studentId', '')).strip()
        wallet = NodeAPI._studentWallet(studentId)
        if wallet is None:
            return jsonify({'error': '请先注册学生身份'}), 400
        title = str(values.get('title', '')).strip()
        desc = str(values.get('desc', '')).strip()
        try:
            hours = float(values.get('hours', 0))
        except (TypeError, ValueError):
            return jsonify({'error': '时长必须是数字'}), 400
        if not title:
            return jsonify({'error': '请填写任务名称'}), 400
        if hours <= 0:
            return jsonify({'error': '时长必须大于 0'}), 400
        tx = wallet.createTransaction(
            node.wallet.publicKeyString(), hours, 'VOL_TASK',
            {'title': title, 'hours': hours, 'desc': desc, 'studentId': studentId})
        node.handleTransactions(tx)
        return jsonify(tx.toJson()), 201

    @route('/api/student/volJoin', methods=['POST'])
    def studentVolJoin(self):
        """学生接志愿服务任务"""
        values = request.get_json(silent=True) or {}
        studentId = str(values.get('studentId', '')).strip()
        wallet = NodeAPI._studentWallet(studentId)
        if wallet is None:
            return jsonify({'error': '请先注册学生身份'}), 400
        taskId = str(values.get('taskId', '')).strip()
        task = None
        for item in NodeAPI._allTransactions():
            tx = item['tx']
            if tx.type == 'VOL_TASK' and tx.id == taskId:
                task = NodeAPI._taskInfo(tx)
                break
        if task is None:
            return jsonify({'error': '任务不存在'}), 404
        if task['joined']:
            return jsonify({'error': '该任务已被接单'}), 400
        if task['publisher'] == studentId:
            return jsonify({'error': '不能接自己发布的任务'}), 400
        tx = wallet.createTransaction(
            node.wallet.publicKeyString(), task['hours'], 'VOL_JOIN',
            {'taskId': taskId, 'title': task['title'], 'hours': task['hours'],
             'studentId': studentId})
        node.handleTransactions(tx)
        return jsonify(tx.toJson()), 201

    @route('/api/student/volTasks', methods=['GET'])
    def studentVolTasks(self):
        """志愿任务市场：全部任务（含接单状态与发布者诚信）"""
        tasks = []
        seen = set()
        for item in NodeAPI._allTransactions():
            tx = item['tx']
            if tx.type == 'VOL_TASK' and tx.id not in seen:
                seen.add(tx.id)
                info = NodeAPI._taskInfo(tx)
                info['onchain'] = item['onchain']
                tasks.append(info)
        tasks.sort(key=lambda t: t['time'], reverse=True)
        return jsonify(tasks), 200

    # ================= 学生端：社团与竞赛 =================

    @route('/api/student/club', methods=['POST'])
    def studentClub(self):
        values = request.get_json(silent=True) or {}
        studentId = str(values.get('studentId', '')).strip()
        wallet = NodeAPI._studentWallet(studentId)
        if wallet is None:
            return jsonify({'error': '请先注册学生身份'}), 400
        club = str(values.get('club', '')).strip()
        role = str(values.get('role', '成员')).strip()
        if not club:
            return jsonify({'error': '请填写社团名称'}), 400
        tx = wallet.createTransaction(
            node.wallet.publicKeyString(), 1, 'CLUB',
            {'club': club, 'role': role, 'studentId': studentId})
        node.handleTransactions(tx)
        return jsonify(tx.toJson()), 201

    @route('/api/student/competition', methods=['POST'])
    def studentCompetition(self):
        values = request.get_json(silent=True) or {}
        studentId = str(values.get('studentId', '')).strip()
        wallet = NodeAPI._studentWallet(studentId)
        if wallet is None:
            return jsonify({'error': '请先注册学生身份'}), 400
        competition = str(values.get('competition', '')).strip()
        award = str(values.get('award', '')).strip()
        if not competition:
            return jsonify({'error': '请填写竞赛名称'}), 400
        tx = wallet.createTransaction(
            node.wallet.publicKeyString(), 1, 'COMPETITION',
            {'competition': competition, 'award': award, 'studentId': studentId})
        node.handleTransactions(tx)
        return jsonify(tx.toJson()), 201

    # ================= 学生端：经费与助学奖金 =================

    @route('/api/student/fundApply', methods=['POST'])
    def studentFundApply(self):
        values = request.get_json(silent=True) or {}
        studentId = str(values.get('studentId', '')).strip()
        wallet = NodeAPI._studentWallet(studentId)
        if wallet is None:
            return jsonify({'error': '请先注册学生身份'}), 400
        reason = str(values.get('reason', '')).strip()
        try:
            amount = int(values.get('amount', 0))
        except (TypeError, ValueError):
            return jsonify({'error': '金额必须是整数'}), 400
        if not reason:
            return jsonify({'error': '请填写申请理由'}), 400
        if amount <= 0:
            return jsonify({'error': '金额必须大于 0'}), 400
        tx = wallet.createTransaction(
            node.wallet.publicKeyString(), amount, 'FUND_APPLY',
            {'reason': reason, 'amount': amount, 'studentId': studentId, 'status': 'pending'})
        NodeAPI.fundStatus[tx.id] = 'pending'
        node.handleTransactions(tx)
        return jsonify(tx.toJson()), 201

    @route('/api/student/funds', methods=['GET'])
    def studentFunds(self):
        studentId = request.args.get('studentId', '')
        funds = []
        for item in NodeAPI._allTransactions():
            tx = item['tx']
            if tx.type == 'FUND_APPLY' and tx.extra.get('studentId') == studentId:
                funds.append(NodeAPI._fundInfo(tx))
            elif tx.type == 'FUND_GRANT' and tx.extra.get('studentId') == studentId:
                funds.append(NodeAPI._fundInfo(tx))
        funds.sort(key=lambda f: f['time'], reverse=True)
        return jsonify(funds), 200

    # ================= 学生端：账本 =================

    @route('/api/student/ledger', methods=['GET'])
    def studentLedger(self):
        studentId = request.args.get('studentId', '')
        wallet = NodeAPI._studentWallet(studentId)
        if wallet is None:
            return jsonify({'error': '请先注册学生身份'}), 400
        pub = wallet.publicKeyString()
        records = []
        for item in NodeAPI._allTransactions():
            tx = item['tx']
            if tx.senderpublickey != pub:
                continue
            record = {
                'type': tx.type,
                'amount': tx.amount,
                'time': tx.timestamp,
                'onchain': item['onchain'],
                'txId': tx.id
            }
            if tx.type in ('BOOK', 'ITEM'):
                record['title'] = tx.extra.get('title', '')
            elif tx.type == 'BUY':
                record['title'] = tx.extra.get('title', '')
                record['role'] = '卖家' if tx.extra.get('seller') == studentId else '买家'
            elif tx.type == 'VOLUNTEER':
                record['project'] = tx.extra.get('project', '')
                record['hours'] = tx.extra.get('hours', tx.amount)
            elif tx.type == 'VOL_JOIN':
                record['title'] = '接单：' + tx.extra.get('title', '')
                record['hours'] = tx.extra.get('hours', tx.amount)
            elif tx.type == 'VOL_TASK':
                record['title'] = '发布任务：' + tx.extra.get('title', '')
            elif tx.type == 'CLUB':
                record['title'] = tx.extra.get('club', '')
                record['role'] = tx.extra.get('role', '成员')
            elif tx.type == 'COMPETITION':
                record['title'] = tx.extra.get('competition', '')
                record['award'] = tx.extra.get('award', '')
            elif tx.type == 'FUND_APPLY':
                record['title'] = '资助申请：' + tx.extra.get('reason', '')
                record['status'] = NodeAPI.fundStatus.get(tx.id, 'pending')
            elif tx.type == 'FUND_GRANT':
                record['title'] = '资助发放：' + tx.extra.get('reason', '')
            records.append(record)
        records.sort(key=lambda r: r['time'], reverse=True)
        rep = NodeAPI._studentReputation(studentId)
        return jsonify({
            'records': records,
            'totalHours': rep['hours'],
            'totalRecords': rep['count'],
            'reputation': rep['reputation'],
            'level': rep['level']
        }), 200

    # ================= 平台管控：只供后台查看与审批 =================

    @route('/api/admin/students', methods=['GET'])
    def adminStudents(self):
        """学生诚信榜（平台视角）"""
        students = []
        for studentId, info in NodeAPI.studentWallets.items():
            rep = NodeAPI._studentReputation(studentId)
            students.append({
                'studentId': studentId,
                'name': info['name'],
                'chainId': info['wallet'].publicKeyString().split('\n')[1][:16] + '...',
                'reputation': rep['reputation'],
                'level': rep['level'],
                'hours': rep['hours'],
                'count': rep['count']
            })
        students.sort(key=lambda s: s['reputation'], reverse=True)
        return jsonify(students), 200

    @route('/api/admin/records', methods=['GET'])
    def adminRecords(self):
        """全平台行为流水（平台视角）"""
        records = []
        for item in NodeAPI._allTransactions():
            tx = item['tx']
            sid = tx.extra.get('studentId', '') if tx.extra else ''
            if tx.type == 'BUY':
                sid = tx.extra.get('buyer', '')
            content = ''
            if tx.type in ('BOOK', 'ITEM'):
                content = tx.extra.get('title', '')
            elif tx.type == 'BUY':
                content = '购买《' + tx.extra.get('title', '') + '》'
            elif tx.type == 'VOLUNTEER':
                content = tx.extra.get('project', '')
            elif tx.type == 'VOL_JOIN':
                content = '接单 ' + tx.extra.get('title', '')
            elif tx.type == 'VOL_TASK':
                content = '发布任务 ' + tx.extra.get('title', '')
            elif tx.type == 'CLUB':
                content = tx.extra.get('club', '')
            elif tx.type == 'COMPETITION':
                content = tx.extra.get('competition', '')
            elif tx.type == 'FUND_APPLY':
                content = '资助申请 ' + tx.extra.get('reason', '')
            elif tx.type == 'FUND_GRANT':
                content = '资助发放 ' + tx.extra.get('reason', '')
            records.append({
                'type': tx.type,
                'studentId': sid,
                'content': content,
                'amount': tx.amount,
                'time': tx.timestamp,
                'onchain': item['onchain'],
                'txId': tx.id
            })
        records.sort(key=lambda r: r['time'], reverse=True)
        return jsonify(records[:200]), 200

    @route('/api/admin/orders', methods=['GET'])
    def adminOrders(self):
        """市集订单管理（平台视角）"""
        items = []
        seen = set()
        for item in NodeAPI._allTransactions():
            tx = item['tx']
            if tx.type in ('BOOK', 'ITEM') and tx.id not in seen:
                seen.add(tx.id)
                info = NodeAPI._itemInfo(tx)
                info['onchain'] = item['onchain']
                items.append(info)
        items.sort(key=lambda b: b['time'], reverse=True)
        return jsonify(items), 200

    @route('/api/admin/funds', methods=['GET'])
    def adminFunds(self):
        """资助/奖助金申请审批列表（平台视角）"""
        funds = []
        for item in NodeAPI._allTransactions():
            tx = item['tx']
            if tx.type == 'FUND_APPLY':
                funds.append(NodeAPI._fundInfo(tx))
        funds.sort(key=lambda f: (0 if f['status'] == 'pending' else 1, -f['time']))
        return jsonify(funds), 200

    @route('/api/admin/fundReview', methods=['POST'])
    def adminFundReview(self):
        """平台审批资助申请：通过 → 生成资助发放存证；驳回 → 记录状态"""
        values = request.get_json(silent=True) or {}
        applyId = str(values.get('applyId', '')).strip()
        approve = bool(values.get('approve', False))
        if applyId not in NodeAPI.fundStatus:
            return jsonify({'error': '申请不存在或已处理'}), 404
        if NodeAPI.fundStatus[applyId] != 'pending':
            return jsonify({'error': '该申请已处理'}), 400
        applyTx = None
        for item in NodeAPI._allTransactions():
            tx = item['tx']
            if tx.type == 'FUND_APPLY' and tx.id == applyId:
                applyTx = tx
                break
        if applyTx is None:
            return jsonify({'error': '申请记录不在链上'}), 404
        if approve:
            studentId = applyTx.extra.get('studentId', '')
            amount = applyTx.extra.get('amount', applyTx.amount)
            reason = applyTx.extra.get('reason', '')
            grant = node.wallet.createTransaction(
                applyTx.senderpublickey, amount, 'FUND_GRANT',
                {'applyId': applyId, 'amount': amount, 'reason': reason,
                 'studentId': studentId, 'status': 'approved'})
            node.handleTransactions(grant)
            NodeAPI.fundStatus[applyId] = 'approved'
            return jsonify({'status': 'approved', 'grantTxId': grant.id}), 200
        NodeAPI.fundStatus[applyId] = 'rejected'
        return jsonify({'status': 'rejected'}), 200
