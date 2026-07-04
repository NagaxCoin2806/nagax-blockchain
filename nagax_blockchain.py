import hashlib
import time
import json
import os
import requests
from ecdsa import SigningKey, VerifyingKey, SECP256k1
from flask import Flask, jsonify, request, render_template

class Bloco:
    def __init__(self, indice, hash_anterior, transacoes, dificuldade, timestamp=None, nonce=0, hash_bloco=None):
        self.indice = indice
        self.hash_anterior = hash_anterior
        self.transacoes = transacoes  
        self.timestamp = timestamp if timestamp else time.time()
        self.nonce = nonce
        self.dificuldade = dificuldade
        self.hash = hash_bloco if hash_bloco else self.calcular_hash()

    def calcular_hash(self):
        conteudo = f"{self.indice}{self.hash_anterior}{json.dumps(self.transacoes, sort_keys=True)}{self.timestamp}{self.nonce}"
        return hashlib.sha256(conteudo.encode()).hexdigest()

    def minerar_bloco(self):
        alvo = "0" * self.dificuldade
        while self.hash[:self.dificuldade] != alvo:
            self.nonce += 1
            self.hash = self.calcular_hash()
        return self.hash

    def to_dict(self):
        return {
            "indice": self.indice,
            "hash_anterior": self.hash_anterior,
            "transacoes": self.transacoes,
            "timestamp": self.timestamp,
            "nonce": self.nonce,
            "dificuldade": self.dificuldade,
            "hash": self.hash
        }


class Blockchain:
    def __init__(self, dificuldade_inicial=3, arquivo_backup="blockchain_nagax.json"):
        self.cadeia = []
        self.nos = set()  
        self.dificuldade = dificuldade_inicial
        self.transacoes_pendentes = []
        self.recompensa_base = 50.0
        self.taxa_percentual = 0.01  # 1% de taxa comercial
        self.arquivo_backup = arquivo_backup
        
        if not self.carregar_do_disco():
            self.criar_bloco_genese()

    def criar_bloco_genese(self):
        bloco_genese = Bloco(0, "0", [{"remetente": "REDE (Coinbase)", "destinatario": "Criador", "quantidade": 100.0, "taxa": 0.0, "assinatura": "GENESE"}], self.dificuldade)
        bloco_genese.minerar_bloco()
        self.cadeia.append(bloco_genese)
        self.salvar_no_disco()

    def obter_ultimo_bloco(self):
        return self.cadeia[-1]

    def registrar_no(self, endereco):
        endereco_limpo = endereco.replace("http://", "").replace("/", "")
        self.nos.add(endereco_limpo)

    def calcular_recompensa_atual(self):
        """ Halving baseado em tempo real: A recompensa cai pela metade a cada 2 anos """
        if len(self.cadeia) <= 1:
            return self.recompensa_base

        tempo_inicial = self.cadeia[0].timestamp
        tempo_atual = self.obter_ultimo_bloco().timestamp
        tempo_decorrido = max(tempo_atual - tempo_inicial, 0)
        
        # 2 anos em segundos (365 * 2 * 24 * 60 * 60)
        dois_anos_em_segundos = 63072000
        
        num_halvings = int(tempo_decorrido // dois_anos_em_segundos)
        num_halvings = min(num_halvings, 64)  # Limite de segurança contra divisão infinita
        
        return self.recompensa_base / (2 ** num_halvings)

    def obter_saldo(self, endereco_publico_hex):
        saldo = 0.0
        for bloco in self.cadeia:
            for tx in bloco.transacoes:
                if isinstance(tx, dict):
                    if tx["remetente"] == endereco_publico_hex:
                        saldo -= tx["quantidade"]
                        if "taxa" in tx: saldo -= tx["taxa"]
                    if tx["destinatario"] == endereco_publico_hex:
                        saldo += tx["quantidade"]
                    if tx.get("minerador_taxa") == endereco_publico_hex:
                        saldo += tx.get("taxa", 0.0)
        return saldo

    # === FUNÇÕES DE VALIDAÇÃO INCORPORADAS ===
    def calcular_hash_bloco_externo(self, bloco):
        conteudo = f"{bloco['indice']}{bloco['hash_anterior']}{json.dumps(bloco['transacoes'], sort_keys=True)}{bloco['timestamp']}{bloco['nonce']}"
        return hashlib.sha256(conteudo.encode()).hexdigest()

    def validar_bloco_externo(self, bloco_novo):
        ultimo_bloco = self.obter_ultimo_bloco()
        
        # 1. Valida se a sequência lógica faz sentido
        if bloco_novo['indice'] != ultimo_bloco.indice + 1:
            return False
        if bloco_novo['hash_anterior'] != ultimo_bloco.hash:
            return False
            
        # 2. Recalcula o Hash para checar adulteração de dados
        hash_recalculado = self.calcular_hash_bloco_externo(bloco_novo)
        if bloco_novo['hash'] != hash_recalculado:
            return False
            
        # 3. Valida a dificuldade da Prova de Trabalho (Proof of Work)
        alvo = "0" * bloco_novo['dificuldade']
        if not hash_recalculado.startswith(alvo):
            return False
            
        return True

    def validar_cadeia(self, cadeia_para_validar):
        bloco_anterior = cadeia_para_validar[0]
        indice_atual = 1
        
        while indice_atual < len(cadeia_para_validar):
            bloco_dados = cadeia_para_validar[indice_atual]
            bloco = Bloco(bloco_dados['indice'], bloco_dados['hash_anterior'], bloco_dados['transacoes'], bloco_dados['dificuldade'], bloco_dados['timestamp'], bloco_dados['nonce'], bloco_dados['hash'])
            
            if bloco.hash != bloco.calcular_hash():
                return False
            if bloco.hash_anterior != bloco_anterior['hash']:
                return False
            alvo = "0" * bloco.dificuldade
            if bloco.hash[:bloco.dificuldade] != alvo:
                return False
                
            bloco_anterior = bloco_dados
            indice_atual += 1
        return True

    def resolver_consenso(self):
        vizinhos = self.nos
        nova_cadeia = None
        maior_comprimento = len(self.cadeia)

        for no in vizinhos:
            try:
                resposta = requests.get(f'http://{no}/chain', timeout=2)
                if resposta.status_code == 200:
                    dados = resposta.json()
                    comprimento = dados['comprimento']
                    cadeia_vizinha = dados['cadeia']

                    if comprimento > maior_comprimento and self.validar_cadeia(cadeia_vizinha):
                        maior_comprimento = comprimento
                        nova_cadeia = cadeia_vizinha
            except requests.exceptions.RequestException:
                continue

        if nova_cadeia:
            self.cadeia = []
            for d in nova_cadeia:
                self.cadeia.append(Bloco(d["indice"], d["hash_anterior"], d["transacoes"], d["dificuldade"], d["timestamp"], d["nonce"], d["hash"]))
            self.salvar_no_disco()
            return True
        return False

    def adicionar_transacao(self, remetente_public_hex, destinatario_public_hex, quantidade, assinatura_hex=None):
        taxa = round(quantidade * self.taxa_percentual, 4) if remetente_public_hex != "REDE (Coinbase)" else 0.0
        tx = {"remetente": remetente_public_hex, "destinatario": destinatario_public_hex, "quantidade": quantidade, "taxa": taxa}

        if remetente_public_hex == "REDE (Coinbase)":
            tx["assinatura"] = "COINBASE_SIGN"
            self.transacoes_pendentes.append(tx)
            return True, "Coinbase registrada."

        if self.obter_saldo(remetente_public_hex) < (quantidade + taxa):
            return False, "Saldo insuficiente para cobrir o valor e a taxa de 1%!"

        tx["assinatura"] = assinatura_hex
        if self.validar_assinatura_transacao(tx):
            self.transacoes_pendentes.append(tx)
            return True, "Transação adicionada à Mempool."
        return False, "Assinatura inválida!"

    def validar_assinatura_transacao(self, tx):
        try:
            chave_publica = VerifyingKey.from_string(bytes.fromhex(tx["remetente"]), curve=SECP256k1)
            tx_hash = hashlib.sha256(f"{tx['remetente']}{tx['destinatario']}{tx['quantidade']}".encode()).digest()
            assinatura = tx["assinatura"]
            try:
                return chave_publica.verify_der(bytes.fromhex(assinatura), tx_hash)
            except:
                return chave_publica.verify(bytes.fromhex(assinatura), tx_hash)
        except:
            return False

    def minerar_transacoes_pendentes(self, endereco_minerador_hex):
        total_taxas = 0.0
        for tx in self.transacoes_pendentes:
            total_taxas += tx.get("taxa", 0.0)
            tx["minerador_taxa"] = endereco_minerador_hex

        recompensa_bloco = self.calcular_recompensa_atual()
        tx_recompensa = {
            "remetente": "REDE (Coinbase)", 
            "destinatario": endereco_minerador_hex, 
            "quantidade": recompensa_bloco + total_taxas, 
            "taxa": 0.0, 
            "info_recompensa": f"Base: {recompensa_bloco} + Taxas: {total_taxas}", 
            "assinatura": "COINBASE_SIGN"
        }
        
        bloco_transacoes = [tx_recompensa] + self.transacoes_pendentes
        novo_bloco = Bloco(len(self.cadeia), self.obter_ultimo_bloco().hash, bloco_transacoes, self.dificuldade)
        novo_bloco.minerar_bloco()
        
        self.cadeia.append(novo_bloco)
        self.transacoes_pendentes = []
        self.salvar_no_disco()
        return novo_bloco

    def salvar_no_disco(self):
        with open(self.arquivo_backup, "w") as f:
            json.dump([bloco.to_dict() for bloco in self.cadeia], f, indent=4)

    def carregar_do_disco(self):
        if os.path.exists(self.arquivo_backup):
            try:
                with open(self.arquivo_backup, "r") as f:
                    dados_blocos = json.load(f)
                    self.cadeia = []
                    for dados in dados_blocos:
                        self.cadeia.append(Bloco(dados["indice"], dados["hash_anterior"], dados["transacoes"], dados["dificuldade"], dados["timestamp"], dados["nonce"], dados["hash"]))
                return True
            except: return False
        return False


# --- ENGINE FLASK ---
app = Flask(__name__)
rede_ngp = Blockchain()

@app.route('/', methods=['GET'])
def pagina_inicial():
    return render_template('index.html')

@app.route('/chain', methods=['GET'])
def obter_blockchain():
    return jsonify({
        'comprimento': len(rede_ngp.cadeia), 
        'recompensa_bloco_atual': rede_ngp.calcular_recompensa_atual(),
        'cadeia': [b.to_dict() for b in rede_ngp.cadeia], 
        'mempool': rede_ngp.transacoes_pendentes
    }), 200

@app.route('/mine', methods=['GET'])
def minerar():
    end = request.args.get('endereco')
    if not end: return jsonify({'erro': 'Falta endereço'}), 400
    bloco = rede_ngp.minerar_transacoes_pendentes(end)
    return jsonify({'mensagem': 'Bloco minerado!', 'dados_bloco': bloco.to_dict()}), 200

# === NOVA ROTA INCORPORADA PARA RECEBER BLOCOS DO SEU HARDWARE ===
@app.route('/blocks/receive', methods=['POST'])
def receber_bloco():
    dados_bloco = request.get_json()
    
    if not dados_bloco:
        return jsonify({"erro": "Dados inválidos ou ausentes"}), 400
        
    if rede_ngp.validar_bloco_externo(dados_bloco):
        # Transforma o dicionário JSON de volta em um Objeto Bloco estruturado
        novo_bloco = Bloco(
            dados_bloco["indice"], 
            dados_bloco["hash_anterior"], 
            dados_bloco["transacoes"], 
            dados_bloco["dificuldade"], 
            dados_bloco["timestamp"], 
            dados_bloco["nonce"], 
            dados_bloco["hash"]
        )
        rede_ngp.cadeia.append(novo_bloco)
        
        # Limpa as transações da Mempool local baseando-se nas assinaturas processadas
        assinaturas_mineradas = [tx.get('assinatura') for tx in dados_bloco['transacoes']]
        rede_ngp.transacoes_pendentes = [tx for tx in rede_ngp.transacoes_pendentes if tx.get('assinatura') not in assinaturas_mineradas]
        
        rede_ngp.salvar_no_disco()
        return jsonify({"mensagem": "🎉 Bloco validado com sucesso e adicionado à rede!"}), 201
    else:
        return jsonify({"erro": "❌ Bloco inválido! Rejeitado pelo nó principal."}), 400

@app.route('/wallet/create', methods=['GET'])
def criar_carteira():
    sk = SigningKey.generate(curve=SECP256k1)
    return jsonify({'chave_privada_para_guardar': sk.to_string().hex(), 'endereco_publico': sk.verifying_key.to_string().hex()}), 200

@app.route('/balance', methods=['GET'])
def checar_saldo():
    end = request.args.get('endereco')
    if not end: return jsonify({'erro': 'Falta endereço'}), 400
    return jsonify({'saldo': f"{rede_ngp.obter_saldo(end)} NGP"}), 200

@app.route('/transactions/new', methods=['POST'])
def nova_transacao():
    valores = request.get_json()
    if not valores or not all(k in valores for k in ['remetente', 'destinatario', 'quantidade', 'assinatura']):
        return jsonify({'erro': 'Campos ausentes'}), 400
    sucesso, msg = rede_ngp.adicionar_transacao(valores['remetente'], valores['destinatario'], float(valores['quantidade']), valores['assinatura'])
    return jsonify({'mensagem': msg}), 201 if sucesso else 400

@app.route('/nodes/register', methods=['POST'])
def registrar_nos():
    valores = request.get_json()
    nos = valores.get('nodes')
    if not nos: return jsonify({'erro': 'Envie uma lista de nós'}), 400
    for no in nos:
        rede_ngp.registrar_no(no)
    return jsonify({'mensagem': 'Nós adicionados com sucesso', 'total_nodes': list(rede_ngp.nos)}), 201

@app.route('/nodes/resolve', methods=['GET'])
def consenso():
    substituido = rede_ngp.resolver_consenso()
    if substituido:
        return jsonify({'mensagem': 'Nossa cadeia estava desatualizada e foi substituída pela correta.'}), 200
    return jsonify({'mensagem': 'Nossa cadeia já é a oficial e mais longa da rede.'}), 200

if __name__ == '__main__':
    import sys
    porta = int(sys.argv[1]) if len(sys.argv) > 1 else 5000
    rede_ngp.arquivo_backup = f"blockchain_nagax_{porta}.json"
    app.run(host='0.0.0.0', port=porta, debug=True)
