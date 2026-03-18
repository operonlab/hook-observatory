// Cronicle Admin Page -- Users

Class.add(Page.Admin, {

	gosub_users: function (args) {
		// show user list
		app.setWindowTitle(_t('admin_users.user_list'));
		this.div.addClass('loading');
		if (!args.offset) args.offset = 0;
		if (!args.limit) args.limit = 25;
		app.api.post('user/admin_get_users', copy_object(args), this.receive_users.bind(this));
	},

	receive_users: function (resp) {
		// receive page of users from server, render it
		this.lastUsersResp = resp;

		var html = '';
		this.div.removeClass('loading');

		var size = get_inner_window_size();
		var col_width = Math.floor(((size.width * 0.9) + 200) / 7);

		this.users = [];
		if (resp.rows) this.users = resp.rows;

		html += this.getSidebarTabs('users',
			[
				['activity', _t('admin.activity_log')],
				['conf_keys', _t('admin.config_keys')],
				['secrets', _t('admin.secrets')],
				['api_keys', _t('admin.api_keys')],
				['categories', _t('admin.categories')],
				['plugins', _t('admin.plugins')],
				['servers', _t('admin.servers')],
				['users', _t('admin.users')]
			]
		);

		var cols = [_t('admin_users.username'), _t('admin_users.full_name'), _t('admin_users.email_address'), _t('admin_users.account_status'), _t('admin_users.user'), 'Created', 'Actions'];

		// html += '<div style="padding:5px 15px 15px 15px;">';
		html += '<div style="padding:20px 20px 30px 20px">';

		html += '<div class="subtitle">';
		html += _t('admin_users.user_list');
		// html += '<div class="subtitle_widget"><span class="link" onMouseUp="$P().refresh_user_list()"><b>Refresh</b></span></div>';
		html += '<div class="subtitle_widget"><i class="fa fa-search">&nbsp;</i><input type="text" id="fe_ul_search" size="15" placeholder="Find username..." style="border:0px;"/></div>';
		html += '<div class="clear"></div>';
		html += '</div>';

		var self = this;
		html += this.getPaginatedTable(resp, cols, 'user', function (user, idx) {
			var actions = [
				'<span class="link" onMouseUp="$P().edit_user(' + idx + ')"><b>Edit</b></span>',
				'<span class="link" onMouseUp="$P().delete_user(' + idx + ')"><b>Delete</b></span>'
			];
			
			let userType = user.privileges.admin ? 'Admin' : (user.ext_auth ? 'External' : 'Standard');
			if(user.group_auth) userType = userType + ' | Group'

			return [
				'<div class="td_big">' + self.getNiceUsername(user, true, col_width) + '</div>',
				'<div class="ellip" style="max-width:' + col_width + 'px;">' + encode_entities(user.full_name) + '</div>',
				'<div class="ellip" style="max-width:' + col_width + 'px;"><a href="mailto:' + encode_entities(user.email) + '">' + encode_entities(user.email) + '</a></div>',
				user.active ? '<span class="color_label green"><i class="fa fa-check">&nbsp;</i>Active</span>' : '<span class="color_label red"><i class="fa fa-warning">&nbsp;</i>Suspended</span>',
				user.privileges.admin ? `<span class="color_label purple"><i class="fa fa-lock">&nbsp;</i>${userType}</span>` : `<span class="color_label gray">${userType}</span>`,
				'<span title="' + get_nice_date_time(user.created, true) + '">' + get_nice_date(user.created, true) + '</span>',
				actions.join(' | ')
			];
		});

		html += '<div style="height:30px;"></div>';
		html += '<center><table><tr>';
		html += '<td><div class="button" style="width:130px;" onMouseUp="$P().edit_user(-1)"><i class="fa fa-user-plus">&nbsp;&nbsp;</i>' + _t('admin_users.add_user') + '</div></td>';
		html += '</tr></table></center>';

		html += '</div>'; // padding
		html += '</div>'; // sidebar tabs

		this.div.html(html);

		setTimeout(function () {
			$('#fe_ul_search').keypress(function (event) {
				if (event.keyCode == '13') { // enter key
					event.preventDefault();
					$P().do_user_search($('#fe_ul_search').val());
				}
			})
				.blur(function () { app.hideMessage(250); })
				.keydown(function () { app.hideMessage(); });
		}, 1);
	},

	do_user_search: function (username) {
		// see if user exists, edit if so
		app.api.post('user/admin_get_user', { username: username },
			function (resp) {
				Nav.go('Admin?sub=edit_user&username=' + username);
			},
			function (resp) {
				app.doError(_t('admin_users.user_not_found') + username, 10);
			}
		);
	},

	edit_user: function (idx) {
		// jump to edit sub
		if (idx > -1) Nav.go('#Admin?sub=edit_user&username=' + this.users[idx].username);
		else if (app.config.external_users) {
			app.doError(_t('admin_users.users_are_managed_by_an_external_system_'));
		}
		else Nav.go('#Admin?sub=new_user');
	},

	delete_user: function (idx) {
		// delete user from search results
		this.user = this.users[idx];
		this.show_delete_account_dialog();
	},

	gosub_new_user: function (args) {
		// create new user
		var html = '';
		app.setWindowTitle(_t('admin_users.add_new_user'));
		this.div.removeClass('loading');

		html += this.getSidebarTabs('new_user',
			[
				['activity', _t('admin.activity_log')],
				['conf_keys', _t('admin.config_keys')],
				['secrets', _t('admin.secrets')],
				['api_keys', _t('admin.api_keys')],
				['categories', _t('admin.categories')],
				['plugins', _t('admin.plugins')],
				['servers', _t('admin.servers')],
				['users', _t('admin.users')],
				['new_user', _t('admin_users.add_new_user')]
			]
		);

		html += '<div style="padding:20px;"><div class="subtitle">' + _t('admin_users.add_new_user') + '</div></div>';

		html += '<div style="padding:0px 20px 50px 20px">';
		html += '<center><table style="margin:0;">';

		this.user = {
			privileges: copy_object(config.default_privileges)
		};

		html += this.get_user_edit_html();

		// notify user
		html += get_form_table_row(_t('admin_users.notify'), '<input type="checkbox" id="fe_eu_send_email" value="1" checked="checked"/><label for="fe_eu_send_email">Send Welcome Email</label>');
		html += get_form_table_caption(_t('admin_users.select_notification_options_for_the_new_'));
		html += get_form_table_spacer();

		// buttons at bottom
		html += '<tr><td colspan="2" align="center">';
		html += '<div style="height:30px;"></div>';

		html += '<table><tr>';
		html += '<td><div class="button" style="width:120px; font-weight:normal;" onMouseUp="$P().cancel_user_edit()">' + _t('admin_users.cancel') + '</div></td>';
		html += '<td width="50">&nbsp;</td>';
		if (config.debug) {
			html += '<td><div class="button" style="width:120px; font-weight:normal;" onMouseUp="$P().populate_random_user()">' + _t('admin_users.randomize') + '</div></td>';
			html += '<td width="50">&nbsp;</td>';
		}
		html += '<td><div class="button" style="width:120px;" onMouseUp="$P().do_new_user()"><i class="fa fa-user-plus">&nbsp;&nbsp;</i>' + _t('admin_users.create_user') + '</div></td>';
		html += '</tr></table>';

		html += '</td></tr>';

		html += '</table></center>';
		html += '</div>'; // table wrapper div

		html += '</div>'; // sidebar tabs

		this.div.html(html);

		setTimeout(function () {
			$('#fe_eu_username').focus();
		}, 1);
	},

	cancel_user_edit: function () {
		// cancel editing user and return to list
		Nav.go('Admin?sub=users');
	},

	populate_random_user: function () {
		// grab random user data (for testing only)
		var self = this;

		$.ajax({
			url: 'http://api.randomuser.me/',
			dataType: 'json',
			success: function (data) {
				// console.log(data);
				if (data.results && data.results[0] && data.results[0].user) {
					var user = data.results[0].user;
					$('#fe_eu_username').val(user.username);
					$('#fe_eu_email').val(user.email);
					$('#fe_eu_fullname').val(ucfirst(user.name.first) + ' ' + ucfirst(user.name.last));
					$('#fe_eu_send_email').prop('checked', false);
					self.generate_password();
					self.checkUserExists('eu');
				}
			}
		});
	},

	do_new_user: function (force) {
		// create new user
		app.clearError();
		var user = this.get_user_form_json();
		if (!user) return; // error

		// if external auth is checked, password field will be disabled on "create user" form
		// since password can't be null in storage random value will be generated (could be reset by admin later if auth setting will change)
		// no one will know this password and as long as external auth is checked, it won't be ever used.
		if (user.ext_auth) {
			user.password = b64_md5(get_unique_id()).substring(0, 12);
		}

		if (!user.username.length) {
			return app.badField('#fe_eu_username', _t('admin_users.please_enter_a_username_for_the_new_acco'));
		}
		// username should be alphanumeric or email-like (for External Auth)
		if (!user.username.match(/^[\w\.\-]+@?[\w\.\-]+$/)) {
			return app.badField('#fe_eu_username', _t('admin_users.please_make_sure_the_username_contains_o'));
		}
		if (!user.email.length) {
			return app.badField('#fe_eu_email', _t('admin_users.please_enter_an_email_address_where_the_'));
		}
		if (!user.email.match(/^\S+\@\S+$/)) {
			return app.badField('#fe_eu_email', _t('admin_users.the_email_address_you_entered_does_not_a'));
		}
		if (!user.full_name.length) {
			return app.badField('#fe_eu_fullname', _t('admin_users.please_enter_the_user'));
		}
		if (!user.password.length) {
			return app.badField('#fe_eu_password', _t('admin_users.please_enter_a_secure_password_to_protec'));
		}

		user.send_email = $('#fe_eu_send_email').is(':checked') ? 1 : 0;

		this.user = user;

		app.showProgress(1.0, _t('admin_users.creating_user'));
		app.api.post('user/admin_create', user, this.new_user_finish.bind(this));
	},

	new_user_finish: function (resp) {
		// new user created successfully
		app.hideProgress();

		Nav.go('Admin?sub=edit_user&username=' + this.user.username);

		setTimeout(function () {
			app.showMessage('success', _t('admin_users.the_new_user_account_was_created_success'));
		}, 150);
	},

	gosub_edit_user: function (args) {
		// edit user subpage
		this.div.addClass('loading');
		app.api.post('user/admin_get_user', { username: args.username }, this.receive_user.bind(this));
	},

	receive_user: function (resp) {
		// edit existing user
		var html = '';
		app.setWindowTitle(_t('admin_users.editing_user') + (this.args.username) + "\"");
		this.div.removeClass('loading');

		html += this.getSidebarTabs('edit_user',
			[
				['activity', _t('admin.activity_log')],
				['conf_keys', _t('admin.config_keys')],
				['secrets', _t('admin.secrets')],
				['api_keys', _t('admin.api_keys')],
				['categories', _t('admin.categories')],
				['plugins', _t('admin.plugins')],
				['servers', _t('admin.servers')],
				['users', _t('admin.users')],
				['edit_user', _t('admin_users.user')]
			]
		);

		html += '<div style="padding:20px;"><div class="subtitle">Editing User &ldquo;' + (this.args.username) + '&rdquo;</div></div>';

		html += '<div style="padding:0px 20px 50px 20px">';
		html += '<center>';
		html += '<table style="margin:0;">';

		this.user = resp.user;

		html += this.get_user_edit_html();

		html += '<tr><td colspan="2" align="center">';
		html += '<div style="height:30px;"></div>';

		html += '<table><tr>';
		html += '<td><div class="button" style="width:130px; font-weight:normal;" onMouseUp="$P().cancel_user_edit()">' + _t('admin_users.cancel') + '</div></td>';
		html += '<td width="50">&nbsp;</td>';
		html += '<td><div class="button" style="width:130px; font-weight:normal;" onMouseUp="$P().show_delete_account_dialog()">' + _t('admin_users.delete_account') + '</div></td>';
		html += '<td width="50">&nbsp;</td>';
		html += '<td><div class="button" style="width:130px;" onMouseUp="$P().do_save_user()"><i class="fa fa-floppy-o">&nbsp;&nbsp;</i>' + _t('admin_users.save_changes') + '</div></td>';
		html += '</tr></table>';

		html += '</td></tr>';

		html += '</table>';
		html += '</center>';
		html += '</div>'; // table wrapper div

		html += '</div>'; // sidebar tabs

		this.div.html(html);

		setTimeout(function () {
			$('#fe_eu_username').attr('disabled', true);
			$('#fe_eu_extauth').attr('disabled', true);
			$P().setExternalAuth();


			if (app.config.external_users) {
				app.showMessage('warning', _t('admin_users.users_are_managed_by_an_external_system_'));
				// self.div.find('input').prop('disabled', true);
			}
		}, 1);
	},

	do_save_user: function () {
		// create new user
		app.clearError();
		var user = this.get_user_form_json();
		if (!user) return; // error

		// if changing password, give server a hint
		if (user.password) {
			user.new_password = user.password;
			delete user.password;
		}

		this.user = user;

		app.showProgress(1.0, _t('admin_users.saving_user_account'));
		app.api.post('user/admin_update', user, this.save_user_finish.bind(this));
	},

	save_user_finish: function (resp, tx) {
		// new user created successfully
		app.hideProgress();
		app.showMessage('success', _t('admin_users.the_user_was_saved_successfully'));
		window.scrollTo(0, 0);

		// if we edited ourself, update header
		if (this.args.username == app.username) {
			app.user = resp.user;
			app.updateHeaderInfo();
		}

		$('#fe_eu_password').val('');
	},

	show_delete_account_dialog: function () {
		// show dialog confirming account delete action
		var self = this;

		var msg = "Are you sure you want to <b>permanently delete</b> the user account \"" + this.user.username + "\"?  There is no way to undo this action, and no way to recover the data.";

		if (app.config.external_users) {
			msg = "Are you sure you want to delete the user account \"" + this.user.username + "\"?  Users are managed by an external system, so this will have little effect here.";
			// return app.doError("Users are managed by an external system, so you cannot make changes here.");
		}

		app.confirm('<span style="color:red">Delete Account</span>', msg, 'Delete', function (result) {
			if (result) {
				app.showProgress(1.0, _t('admin_users.deleting_account'));
				app.api.post('user/admin_delete', {
					username: self.user.username
				}, self.delete_user_finish.bind(self));
			}
		});
	},

	delete_user_finish: function (resp, tx) {
		// finished deleting, immediately log user out
		var self = this;
		app.hideProgress();

		Nav.go('Admin?sub=users', 'force');

		setTimeout(function () {
			app.showMessage('success', _t('admin_users.the_user_account') + "'" + self.user.username + "' was deleted successfully.");
		}, 150);
	},

	get_user_edit_html: function () {
		// get html for editing a user (or creating a new one)
		var html = '';
		var user = this.user;

		// user id
		html += get_form_table_row('Username',
			'<table cellspacing="0" cellpadding="0"><tr>' +
			'<td><input type="text" id="fe_eu_username" size="20" style="font-size:14px;" value="' + escape_text_field_value(user.username) + '" spellcheck="false" onChange="$P().checkUserExists(\'eu\')"/></td>' +
			'<td><div id="d_eu_valid" style="margin-left:5px; font-weight:bold;"></div></td>' +
			'</tr></table>'
		);
		html += get_form_table_caption(_t('admin_users.enter_the_username_which_identifies_this'));
		html += get_form_table_spacer();

		// account status
		html += get_form_table_row( 'Account Status', '<select id="fe_eu_status">' + render_menu_options([['1','Active'], ['0','Suspended']], user.active) + '</select>' );
		html += get_form_table_caption("'Suspended' means that the account remains in the system, but the user cannot log in.");
		html += get_form_table_spacer();

		// full name
		html += get_form_table_row('Full Name', '<input type="text" id="fe_eu_fullname" size="30" value="' + escape_text_field_value(user.full_name) + '" spellcheck="false"/>');
		html += get_form_table_caption("User's first and last name.  They will not be shared with anyone outside the server.");
		html += get_form_table_spacer();

		// email
		html += get_form_table_row('Email Address', '<input type="text" id="fe_eu_email" size="30" value="' + escape_text_field_value(user.email) + '" spellcheck="false"/>');
		html += get_form_table_caption(_t('admin_users.this_can_be_used_to_recover_the_password'));
		html += get_form_table_spacer();

		// password with ext_auth checkbox

		var pwdDisabledIfExtAuth = user.ext_auth ? "disabled" : ' ';
		var userExtAuthChecked = user.ext_auth ? 'checked="checked"' : ' '

		html += get_form_table_row(user.password ? 'Change Password' : 'Password', `<input type="text" id="fe_eu_password" size="20" value="" spellcheck="false" ${pwdDisabledIfExtAuth}/>&nbsp;<span class="link addme" id="generate_pwd" onMouseUp="$P().generate_password()">&laquo; Generate Random</span>`);
		html += get_form_table_caption(user.password ? "Optionally enter a new password here to reset it.  Please make it secure." : "Enter a password for the account.  Please make it secure.");
		html += get_form_table_row('', `<input type="checkbox" ${userExtAuthChecked} id="fe_eu_extauth" onclick="$P().setExternalAuth()" />`);
		html += get_form_table_caption(_t('admin_users.use_external_authentication_it_cannot_be'));
		html += get_form_table_spacer();

		// privilege list
		var priv_html = '';
		var user_is_admin = !!user.privileges.admin;

		for (var idx = 0, len = config.privilege_list.length; idx < len; idx++) {
			var priv = config.privilege_list[idx];
			var has_priv = !!user.privileges[priv.id];
			var priv_visible = (priv.id == 'admin') || !user_is_admin;
			var priv_class = (priv.id == 'admin') ? 'priv_group_admin' : 'priv_group_other';

			priv_html += '<div class="' + priv_class + '" style="margin-top:4px; margin-bottom:4px; ' + (priv_visible ? '' : 'display:none;') + '">';
			priv_html += '<input type="checkbox" id="fe_eu_priv_' + priv.id + '" value="1" ' +
				(has_priv ? 'checked="checked" ' : '') + ((priv.id == 'admin') ? 'onChange="$P().change_admin_checkbox()"' : '') + '>';
			priv_html += '<label for="fe_eu_priv_' + priv.id + '">' + priv.title + '</label>';
			priv_html += '</div>';
		}

		// user can be limited to certain categories
		var priv = { id: "cat_limit", title: "Limit to Categories" };
		var has_priv = !!user.privileges[priv.id];
		var priv_visible = !user_is_admin;

		priv_html += '<div class="priv_group_other" style="margin-top:4px; margin-bottom:4px; ' + (priv_visible ? '' : 'display:none;') + '">';
		priv_html += '<input type="checkbox" id="fe_eu_priv_' + priv.id + '" value="1" ' +
			(has_priv ? 'checked="checked" ' : '') + 'onChange="$P().change_cat_checkbox()"' + '>';
		priv_html += '<label for="fe_eu_priv_' + priv.id + '">' + priv.title + '</label>';
		priv_html += '</div>';

		priv_html += '<div class="priv_group_other">';

		// sort by title ascending
		var categories = app.categories.sort(function (a, b) {
			// return (b.title < a.title) ? 1 : -1;
			return a.title.toLowerCase().localeCompare(b.title.toLowerCase());
		});


		for (var idx = 0, len = categories.length; idx < len; idx++) {
			var cat = categories[idx];
			var priv = { id: 'cat_' + cat.id, title: cat.title };
			var has_priv = !!user.privileges[priv.id];
			var priv_visible = !!user.privileges.cat_limit;

			priv_html += '<div class="priv_group_cat" style="margin-top:4px; margin-bottom:4px; margin-left:20px; ' + (priv_visible ? '' : 'display:none;') + '">';
			priv_html += '<input type="checkbox" id="fe_eu_priv_' + priv.id + '" value="1" ' +
				(has_priv ? 'checked="checked" ' : '') + '>';
			priv_html += '<label for="fe_eu_priv_' + priv.id + '" style="font-weight:normal"><i class="fa fa-folder-open-o">&nbsp;</i>' + priv.title + '</label>';
			priv_html += '</div>';
		}

		priv_html += '</div>';

		// user can be limited to certain server groups
		var priv = { id: "grp_limit", title: "Limit to Server Groups" };
		var has_priv = !!user.privileges[priv.id];
		var priv_visible = !user_is_admin;

		priv_html += '<div class="priv_group_other" style="margin-top:4px; margin-bottom:4px; ' + (priv_visible ? '' : 'display:none;') + '">';
		priv_html += '<input type="checkbox" id="fe_eu_priv_' + priv.id + '" value="1" ' +
			(has_priv ? 'checked="checked" ' : '') + 'onChange="$P().change_grp_checkbox()"' + '>';
		priv_html += '<label for="fe_eu_priv_' + priv.id + '">' + priv.title + '</label>';
		priv_html += '</div>';

		priv_html += '<div class="priv_group_other">';

		// sort by title ascending
		var groups = app.server_groups.sort(function (a, b) {
			// return (b.title < a.title) ? 1 : -1;
			return a.title.toLowerCase().localeCompare(b.title.toLowerCase());
		});

		for (var idx = 0, len = groups.length; idx < len; idx++) {
			var group = groups[idx];
			var priv = { id: 'grp_' + group.id, title: group.title };
			var has_priv = !!user.privileges[priv.id];
			var priv_visible = !!user.privileges.grp_limit;

			priv_html += '<div class="priv_group_grp" style="margin-top:4px; margin-bottom:4px; margin-left:20px; ' + (priv_visible ? '' : 'display:none;') + '">';
			priv_html += '<input type="checkbox" id="fe_eu_priv_' + priv.id + '" value="1" ' +
				(has_priv ? 'checked="checked" ' : '') + '>';
			priv_html += '<label for="fe_eu_priv_' + priv.id + '" style="font-weight:normal"><i class="fa fa-folder-open-o">&nbsp;</i>' + priv.title + '</label>';
			priv_html += '</div>';
		}

		priv_html += '</div>';

		html += get_form_table_row(_t('admin_users.privileges'), priv_html);
		html += get_form_table_caption(_t('admin_users.select_which_privileges_the_user_account'));
		html += get_form_table_spacer();

		return html;
	},

	change_admin_checkbox: function () {
		// toggle admin checkbox
		var is_checked = $('#fe_eu_priv_admin').is(':checked');
		if (is_checked) $('div.priv_group_other').hide(250);
		else $('div.priv_group_other').show(250);
	},

	change_cat_checkbox: function () {
		// toggle category limit checkbox
		var is_checked = $('#fe_eu_priv_cat_limit').is(':checked');
		if (is_checked) $('div.priv_group_cat').show(250);
		else $('div.priv_group_cat').hide(250);
	},

	change_grp_checkbox: function () {
		// toggle server group limit checkbox
		var is_checked = $('#fe_eu_priv_grp_limit').is(':checked');
		if (is_checked) $('div.priv_group_grp').show(250);
		else $('div.priv_group_grp').hide(250);
	},

	get_user_form_json: function () {
		// get user elements from form, used for new or edit
		var user = {
			username: trim($('#fe_eu_username').val().toLowerCase()),
			active: ($('#fe_eu_status').val() === "1") ? 1 : 0,
			full_name: trim($('#fe_eu_fullname').val()),
			email: trim($('#fe_eu_email').val()),
			password: $('#fe_eu_password').val(),
			ext_auth: $('#fe_eu_extauth').is(":checked"),
			privileges: {}
		};

		user.privileges.admin = $('#fe_eu_priv_admin').is(':checked') ? 1 : 0;

		if (!user.privileges.admin) {
			for (var idx = 0, len = config.privilege_list.length; idx < len; idx++) {
				var priv = config.privilege_list[idx];
				user.privileges[priv.id] = $('#fe_eu_priv_' + priv.id).is(':checked') ? 1 : 0;
			}

			// category limit privs
			user.privileges.cat_limit = $('#fe_eu_priv_cat_limit').is(':checked') ? 1 : 0;

			if (user.privileges.cat_limit) {
				var num_cat_privs = 0;
				for (var idx = 0, len = app.categories.length; idx < len; idx++) {
					var cat = app.categories[idx];
					var priv = { id: 'cat_' + cat.id };
					if ($('#fe_eu_priv_' + priv.id).is(':checked')) {
						user.privileges[priv.id] = 1;
						num_cat_privs++;
					}
				}

				if (!num_cat_privs) return app.doError(_t('admin_users.please_select_at_least_one_category_priv'));
			} // cat limit

			// server group limit privs
			user.privileges.grp_limit = $('#fe_eu_priv_grp_limit').is(':checked') ? 1 : 0;

			if (user.privileges.grp_limit) {
				var num_grp_privs = 0;
				for (var idx = 0, len = app.server_groups.length; idx < len; idx++) {
					var grp = app.server_groups[idx];
					var priv = { id: 'grp_' + grp.id };
					if ($('#fe_eu_priv_' + priv.id).is(':checked')) {
						user.privileges[priv.id] = 1;
						num_grp_privs++;
					}
				}

				if (!num_grp_privs) return app.doError(_t('admin_users.please_select_at_least_one_server_group_'));
			} // grp limit
		} // not admin

		return user;
	},

	generate_password: function () {
		// generate random password
		$('#fe_eu_password').val(b64_md5(get_unique_id()).substring(0, 8));
	},

	// this will enbale/disable password field based on "ext_auth" checkbox
	setExternalAuth: function () {
		let pwd = $("#fe_eu_password")
		let checkBox = $("#fe_eu_extauth")
		let genButton = $("#generate_pwd")
		if (checkBox.is(':checked')) {
			pwd.val(' '); // set blank password if checked. It will be replcaed with random value on submitting
			pwd.prop('disabled', true);
			genButton.hide();
		} else {
			pwd.prop('disabled', false);
			genButton.show();
		}
	}

});
