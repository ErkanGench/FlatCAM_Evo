
# Install on Ubuntu(-like) systems

# Install the system libraries (apt, asks for sudo) and the Python modules (in the .venv folder of the project)
install_dependencies:
	./setup_ubuntu.sh

USER_ID = $(shell id -u)

LOCAL_PATH = $(shell pwd)
LOCAL_APPS_PATH = ~/.local/share/applications
ASSEST_PATH = assets/linux

INSTALL_PATH = /usr/share/flatcam-beta
APPS_PATH = /usr/share/applications
LOCAL_MIME_PATH = ~/.local/share/mime
MIME_PATH = /usr/share/mime/packages

MIN_PY3_MINOR_VERSION := 10
# required version
MIN_PY3_MINOR_VERSION := $(shell python3 -c 'import sys; print($(MIN_PY3_MINOR_VERSION))')

# current version minimized to required (to allow ifneq test)
PY3_MIN_MINOR_VERSION := $(shell python3 -c 'import sys; print(min($(MIN_PY3_MINOR_VERSION),sys.version_info.minor))')

ifneq ($(MIN_PY3_MINOR_VERSION), $(PY3_MIN_MINOR_VERSION))
    $(info Current python version is 3.$(PY3_MIN_MINOR_VERSION))
    $(error You must have at least 3.$(MIN_PY3_MINOR_VERSION) installed)
endif

install:
ifeq ($(USER_ID), 0)
	@ echo "Installing it system-wide"
	cp -rf $(LOCAL_PATH) $(INSTALL_PATH)
	@ sed -i "s|python_script_path=.*|python_script_path=$(INSTALL_PATH)|g" $(INSTALL_PATH)/assets/linux/flatcam-beta
	ln -sf $(INSTALL_PATH)/assets/linux/flatcam-beta /usr/local/bin
	cp -f $(ASSEST_PATH)/flatcam-beta.desktop $(APPS_PATH)
	@ sed -i "s|Exec=.*|Exec=$(INSTALL_PATH)/$(ASSEST_PATH)/flatcam-beta %F|g" $(APPS_PATH)/flatcam-beta.desktop
	@ sed -i "s|Icon=.*|Icon=$(INSTALL_PATH)/$(ASSEST_PATH)/icon.png|g" $(APPS_PATH)/flatcam-beta.desktop
	mkdir -p $(MIME_PATH)
	cp -f $(ASSEST_PATH)/flatcam-mime.xml $(MIME_PATH)/flatcam-beta.xml
	-update-mime-database /usr/share/mime
	-update-desktop-database $(APPS_PATH)
else
	@ echo "Installing locally for $(USER) only"
	cp -f $(ASSEST_PATH)/flatcam-beta.desktop $(LOCAL_APPS_PATH)
	@ sed -i "s|Exec=.*|Exec=$(LOCAL_PATH)/$(ASSEST_PATH)/flatcam-beta %F|g" $(LOCAL_APPS_PATH)/flatcam-beta.desktop
	@ sed -i "s|Icon=.*|Icon=$(LOCAL_PATH)/$(ASSEST_PATH)/icon.png|g" $(LOCAL_APPS_PATH)/flatcam-beta.desktop
	mkdir -p $(LOCAL_MIME_PATH)/packages
	cp -f $(ASSEST_PATH)/flatcam-mime.xml $(LOCAL_MIME_PATH)/packages/flatcam-beta.xml
	-update-mime-database $(LOCAL_MIME_PATH)
	-update-desktop-database $(LOCAL_APPS_PATH)
endif

remove:
ifeq ($(USER_ID), 0)
	@ echo "Uninstalling it system-wide"
	rm -rf $(INSTALL_PATH)
	rm -f /usr/local/bin/flatcam-beta
	rm -r $(APPS_PATH)/flatcam-beta.desktop
	rm -f $(MIME_PATH)/flatcam-beta.xml
	-update-mime-database /usr/share/mime
else
	@ echo "Uninstalling only for $(USER) user"
	rm -f $(LOCAL_APPS_PATH)/flatcam-beta.desktop
	rm -f $(LOCAL_MIME_PATH)/packages/flatcam-beta.xml
	-update-mime-database $(LOCAL_MIME_PATH)
endif
