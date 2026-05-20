
# DFIR-Ogre
[![badge_repo](https://img.shields.io/badge/ANSSI--FR-DFIR--Ogre-white)](https://github.com/ANSSI-FR/dfir-ogre)
[![category_badge_external](https://img.shields.io/badge/category-external-%23b556b6)](https://anssi-fr.github.io/README.en.html#project-categories)
[![openess_badge_A](https://img.shields.io/badge/code.gouv.fr-collaborative-blue)](https://anssi-fr.github.io/README.en.html#openness-level)

**DFIR-OGRE** is a command‑line utility that extracts windows forensic artefact from [DFIR-ORC](https://github.com/DFIR-ORC/dfir-orc) archives into structured data that can be consumed by Splunk, ELK or other databases.

It provides a collection of **plug‑ins**, each dedicated to parsing a specific class of Windows artefacts. 
The built‑in plug‑ins cover a lot of artefact that appears in a typical DFIR-ORC archive:
* **Application Specific** – shortcut (`.lnk`) files, Java download index, etc.  
* **Browser artefacts** – Chrome and Firefox extensions, download histories, and general browsing history.  
* **File system** – NTFS information, USN journal entries, recycle‑bin records, etc. 
* **Processes and applications** – AmCache, scheduled tasks, Shell Bags, Prefetch Files, Orc processes, etc.
* **System logs** – Windows Event logs (EVTX), Windows Error Reporting files, SRUM usage databases, etc.


## ⚠️ Beta Status
This software is currently in **beta**. While functional and actively developed, it may still undergo breaking changes, and some artefact parsers may not yet be fully stabilized. We welcome feedback, bug reports, and contributions using the [issue tracker](https://github.com/ANSSI-FR/dfir-ogre/issues).


## Documentation

The full documentation is available on the website : https://dfir-oger.github.io

## Installation

### Prerequisites

| Item | Minimum version |
|------|-----------------|
| **Python** | 3.10 or newer |
| **git** | any recent version |
| **uv** | ≥ 0.4 (installable with `pip`)


### Clone and install the repositories

```bash
# Choose a location 
mkdir -p ~/dfir-ogre && cd ~/dfir-ogre

git clone https://github.com/ANSSI-FR/dfir-ogre-plugin-windows.git
git clone git@github.com/ANSSI-FR/dfir-ogre.git

#create the virtual environment
uv venv 
uv pip install ./dfir-ogre

# Activate the virtual environment
source .venv/bin/activate
```

The prompt should now show the venv name, e.g. `(dfir-ogre) $`.

and the `dfir-ogre` command should be available
```bash
dfir-ogre --help 
```

## Usage example

Extract a DFIR-ORC archive from its Outcome.json file, using the ogre.yaml configuration.

```bash
dfir-ogre orc \
    --archive ORC_xxx_Outcome.json \
    --case sample_case \
    --configuration dfir-ogre/configuration/ogre.yaml
```

## French Cybersecurity Agency (ANSSI)
<img src="https://www.sgdsn.gouv.fr/files/styles/ds_image_paragraphe/public/files/Notre_Organisation/logo_anssi.png" alt="ANSSI logo" width="25%">
    
*This projet is managed by [ANSSI](https://cyber.gouv.fr/). To find out more, you can visit the [page](https://cyber.gouv.fr/enjeux-technologiques/open-source/) (in French) dedicated to ANSSI’s open-source strategy. You can also click on the badges above to learn more about their meaning.*
