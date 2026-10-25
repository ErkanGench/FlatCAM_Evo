
# Install on Ubuntu(-like) systems

# Install the system libraries (apt, asks for sudo) and the Python modules (in the .venv folder of the project)
install_dependencies:
	./setup_ubuntu.sh

USER_ID = $(shell id -u)

LOCAL_PATH = $(CURDIR)
LOCAL_APPS_PATH = $(HOME)/.local/share/applications
ASSET_PATH = assets/linux
LOCAL_BIN_PATH = $(HOME)/.local/bin
LOCAL_MAN_PATH = $(HOME)/.local/share/man/man1

INSTALL_PATH = /usr/share/flatcam-evo
APPS_PATH = /usr/share/applications
LOCAL_MIME_PATH = $(HOME)/.local/share/mime
MIME_PATH = /usr/share/mime/packages
MAN_PATH = /usr/local/share/man/man1

.PHONY: install_dependencies install remove

install:
ifeq ($(USER_ID), 0)
	@ echo "Installing it system-wide"
	mkdir -p "$(INSTALL_PATH)" "$(APPS_PATH)" /usr/local/bin "$(MIME_PATH)" "$(MAN_PATH)"
	cp -rf "$(LOCAL_PATH)/." "$(INSTALL_PATH)/"
	chmod +x "$(INSTALL_PATH)/$(ASSET_PATH)/flatcam-evo"
	ln -sf "$(INSTALL_PATH)/$(ASSET_PATH)/flatcam-evo" /usr/local/bin/flatcam-evo
	cp -f "$(ASSET_PATH)/flatcam-evo.desktop" "$(APPS_PATH)/flatcam-evo.desktop"
	@ sed -i 's|Exec=.*|Exec="$(INSTALL_PATH)/$(ASSET_PATH)/flatcam-evo" %F|g' "$(APPS_PATH)/flatcam-evo.desktop"
	@ sed -i 's|Icon=.*|Icon=$(INSTALL_PATH)/$(ASSET_PATH)/icon.png|g' "$(APPS_PATH)/flatcam-evo.desktop"
	cp -f "$(ASSET_PATH)/flatcam-mime.xml" "$(MIME_PATH)/flatcam-evo.xml"
	install -m 644 flatcam-evo.1 "$(MAN_PATH)/flatcam-evo.1"
	-update-mime-database /usr/share/mime
	-update-desktop-database "$(APPS_PATH)"
else
	@ echo "Installing locally for $(USER) only"
	mkdir -p "$(LOCAL_APPS_PATH)" "$(LOCAL_BIN_PATH)" "$(LOCAL_MIME_PATH)/packages" "$(LOCAL_MAN_PATH)"
	chmod +x "$(LOCAL_PATH)/$(ASSET_PATH)/flatcam-evo"
	ln -sf "$(LOCAL_PATH)/$(ASSET_PATH)/flatcam-evo" "$(LOCAL_BIN_PATH)/flatcam-evo"
	cp -f "$(ASSET_PATH)/flatcam-evo.desktop" "$(LOCAL_APPS_PATH)/flatcam-evo.desktop"
	@ sed -i 's|Exec=.*|Exec="$(LOCAL_PATH)/$(ASSET_PATH)/flatcam-evo" %F|g' "$(LOCAL_APPS_PATH)/flatcam-evo.desktop"
	@ sed -i 's|Icon=.*|Icon=$(LOCAL_PATH)/$(ASSET_PATH)/icon.png|g' "$(LOCAL_APPS_PATH)/flatcam-evo.desktop"
	cp -f "$(ASSET_PATH)/flatcam-mime.xml" "$(LOCAL_MIME_PATH)/packages/flatcam-evo.xml"
	install -m 644 flatcam-evo.1 "$(LOCAL_MAN_PATH)/flatcam-evo.1"
	-update-mime-database "$(LOCAL_MIME_PATH)"
	-update-desktop-database "$(LOCAL_APPS_PATH)"
endif

remove:
ifeq ($(USER_ID), 0)
	@ echo "Uninstalling it system-wide"
	rm -rf "$(INSTALL_PATH)"
	rm -f /usr/local/bin/flatcam-evo
	rm -f "$(APPS_PATH)/flatcam-evo.desktop"
	rm -f "$(MIME_PATH)/flatcam-evo.xml" "$(MAN_PATH)/flatcam-evo.1"
	-update-mime-database /usr/share/mime
	-update-desktop-database "$(APPS_PATH)"
else
	@ echo "Uninstalling only for $(USER) user"
	rm -f "$(LOCAL_BIN_PATH)/flatcam-evo" "$(LOCAL_APPS_PATH)/flatcam-evo.desktop"
	rm -f "$(LOCAL_MIME_PATH)/packages/flatcam-evo.xml" "$(LOCAL_MAN_PATH)/flatcam-evo.1"
	-update-mime-database "$(LOCAL_MIME_PATH)"
	-update-desktop-database "$(LOCAL_APPS_PATH)"
endif
