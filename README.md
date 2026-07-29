# Roulez Électrique — Intégration Home Assistant / Home Assistant Integration

Connectez vos bornes de recharge [Roulez Électrique](https://roulezelectrique.club) à Home Assistant : télémétrie en direct, plus le contrôle à distance (démarrer/arrêter, limite de courant, verrou) pour les vendeurs qui le permettent.

Connect your [Roulez Électrique](https://roulezelectrique.club) EV chargers to Home Assistant: live telemetry, plus remote control (start/stop, current limit, lock) for the vendors that support it.

**📖 Documentation complète / Full documentation:**

- 🇫🇷 **[README-FR.md](README-FR.md)** — installation, configuration, entités, limitations, mise à jour
- 🇬🇧 **[README-EN.md](README-EN.md)** — installation, setup, entities, limitations, upgrading

---

**Nouveau / New (v0.7.0) :** Le curseur de courant maximal fonctionne enfin sur les bornes EVduty/Elmec, qui rejetaient jusqu'ici la commande OCPP utilisée. Attention : appliquer une valeur redémarre la borne 30-60 s, et la commande est refusée pendant une recharge. Voir la doc complète ci-dessus.

**New (v0.7.0):** The max-current slider finally works on EVduty/Elmec chargers, which until now rejected the OCPP command it used. Note: applying a value reboots the charger for 30-60 s, and the command is refused while a session is in progress. See the full docs above.

## Licence / License

MIT — see [LICENSE](LICENSE).
