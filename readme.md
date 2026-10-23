# Mag3D2W

Criar virtual env chamada venv dentro do RPi_Proxy_mag3d2w folder e fazer ```pip instal -r requirements.txt```

Apenas é necessário alterar uma setting no código para o deploy de cada uma das experiências:
Lisbon and Lordelo. No topo do ficheiro `magnet_main.py`, alterar:

```python
# CHANGE THIS:
# (BCM GPIO): Lisbon = 6; Lordelo = 25.
ADC_DRDY_PIN = 25
```
Ambas as aquisições usam os endereços ADC `0x48` no magnetometro e `0x1c`. Dá para verificar com o comando: ```sudo i2cdetect -y 1```.



