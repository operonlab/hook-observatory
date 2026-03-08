Class.subclass( Page.Base, "Page.MyAccount", {	
		
	onInit: function() {
		// called once at page load
		var html = '';
		this.div.html( html );
	},
	
	onActivate: function(args) {
		// page activation
		if (!this.requireLogin(args)) return true;
		
		if (!args) args = {};
		this.args = args;
		
		app.setWindowTitle(_t('my_account.my_account'));
		app.showTabBar(true);
		
		this.receive_user({ user: app.user });
		
		return true;
	},
	
	receive_user: function(resp, tx) {
		var self = this;
		var html = '';
		var user = resp.user;
				
		html += '<div style="padding:50px 20px 50px 20px">';
		html += '<center>';
		
		html += '<table><tr>';
			html += '<td valign="top" style="vertical-align:top">';
			
		html += '<table style="margin:0;">';

		let isExternal = user.ext_auth ? ' [External]' : ''
		
		// user id
		html += get_form_table_row( _t('my_account.username'), '<div style="font-size: 14px;"><b>' + app.username + `${isExternal}</b></div>` );
		html += get_form_table_caption( _t('my_account.your_username_cannot_be_changed') );
		html += get_form_table_spacer();
		
		// full name
		html += get_form_table_row( _t('my_account.full_name'), '<input type="text" id="fe_ma_fullname" size="30" value="'+escape_text_field_value(user.full_name)+'"/>' );
		html += get_form_table_caption( _t('my_account.your_first_and_last_names_used_for_displ'));
		html += get_form_table_spacer();
		
		// email
		html += get_form_table_row( _t('my_account.email_address'), '<input type="text" id="fe_ma_email" size="30" value="'+escape_text_field_value(user.email)+'"/>' );
		html += get_form_table_caption( _t('my_account.this_is_used_to_generate_your_profile_pi') );
		html += get_form_table_spacer();
		
		var disableIfExternal = user.ext_auth ? "disabled" : " ";

		if(!user.ext_auth) {

		// current password
		html += get_form_table_row(_t('my_account.current_password'), `<input type="${app.get_password_type()}" id="fe_ma_old_password" size="30" value="" spellcheck="false" ${disableIfExternal}/>` + app.get_password_toggle_html());
		html += get_form_table_caption( _t('my_account.enter_your_current_account_password_to_m') );
		html += get_form_table_spacer();
		
		// reset password
		html += get_form_table_row(_t('my_account.new_password'), `<input type="${app.get_password_type()}" id="fe_ma_new_password" size="30" value="" spellcheck="false" ${disableIfExternal}/>` + app.get_password_toggle_html());
		html += get_form_table_caption( _t('my_account.if_you_need_to_change_your_password_ente') );
		html += get_form_table_spacer();

		}
		
		html += '<tr><td colspan="2" align="center">';
			html += '<div style="height:30px;"></div>';
			
			html += '<table><tr>';
				html += '<td><div class="button" style="width:130px; font-weight:normal;" onMouseUp="$P().show_delete_account_dialog()">' + _t('my_account.delete_account') + '</div></td>';
				html += '<td width="80">&nbsp;</td>';
				html += '<td><div class="button" style="width:130px;" onMouseUp="$P().save_changes()"><i class="fa fa-floppy-o">&nbsp;&nbsp;</i>' + _t('my_account.save_changes') + '</div></td>';
			html += '</tr></table>';
			
		html += '</td></tr>';
		
		html += '</table>';
		html += '</center>';
		
		html += '</td>';
			html += '<td valign="top" align="left" style="vertical-align:top; text-align:left;">';

				// gravar profile image and edit button
				html += '<fieldset style="width:150px; margin-left:40px; border:1px solid #ddd; box-shadow:none;"><legend>' + _t('my_account.profile_picture') + '</legend>';

				if (app.config.external_users) {
					html += '<div id="d_ma_image" style="width:128px; height:128px; margin:5px auto 0 auto;background-size:cover; background-image:url(\'' + app.getUserAvatarURL(128) + '\'); cursor:default;"></div>';
				}
				else {
					html += '<div id="d_ma_image" style="width:128px; height:128px; margin:5px auto 0 auto; background-size:cover; background-image:url(\'' + app.getUserAvatarURL(128) + '\'); cursor:pointer;" onMouseUp="$P().edit_gravatar()"></div>';
					html += '<div class="button mini" style="margin:10px auto 5px auto;" onMouseUp="$P().edit_gravatar()">' + _t('my_account.edit_image') + '</div>';
					html += '<div style="font-size:11px; color:#888; text-align:center; margin-bottom:5px;">Image services provided by <a href="https://en.gravatar.com/connect/" target="_blank">Gravatar.com</a>.</div>';
				}
				html += '</fieldset>';
			html += '</td>';
		html += '</tr></table>';
		
		html += '</div>'; // table wrapper div
				
		this.div.html( html );
		
		setTimeout( function() {
			app.password_strengthify( '#fe_ma_new_password' );
			
			if (app.config.external_users) {
				app.showMessage('warning', _t('my_account.users_are_managed_by_an_external_system_'));
				self.div.find('input').prop('disabled', true);
			}
		}, 1 );
	},
	
	edit_gravatar: function() {
		// edit profile pic at gravatar.com
		window.open( 'https://en.gravatar.com/connect/' );
	},
	
	save_changes: function(force) {
		// save changes to user info
		let user = app.user || {}
		app.clearError();
		if (app.config.external_users || user.ext_auth) {
			return app.doError(_t('my_account.users_are_managed_by_an_external_system_'));
		}
		if (!$('#fe_ma_old_password').val()) return app.badField('#fe_ma_old_password', _t('my_account.please_enter_your_current_account_passwo'));
		
		if ($('#fe_ma_new_password').val() && !force && (app.last_password_strength.score < 3)) {
			app.confirm( '<span style="color:red">Insecure Password Warning</span>', app.get_password_warning(), "Proceed", function(result) {
				if (result) $P().save_changes('force');
			} );
			return;
		} // insecure password
		
		app.showProgress( 1.0, _t('my_account.saving_account') );
		
		app.api.post( 'user/update', {
			username: app.username,
			full_name: trim($('#fe_ma_fullname').val()),
			email: trim($('#fe_ma_email').val()),
			old_password: $('#fe_ma_old_password').val(),
			new_password: $('#fe_ma_new_password').val()
		}, 
		function(resp) {
			// save complete
			app.hideProgress();
			app.showMessage('success', _t('my_account.your_account_settings_were_updated_succe'));
			
			$('#fe_ma_old_password').val('');
			$('#fe_ma_new_password').val('');
			
			app.user = resp.user;
			app.updateHeaderInfo();
			
			$('#d_ma_image').css( 'background-image', 'url(' + app.getUserAvatarURL(128) + ')' );
		} );
	},
	
	show_delete_account_dialog: function() {
		// show dialog confirming account delete action
		var self = this;
		
		app.clearError();
		if (app.config.external_users) {
			return app.doError(_t('my_account.users_are_managed_by_an_external_system_'));
		}
		if (!$('#fe_ma_old_password').val()) return app.badField('#fe_ma_old_password', _t('my_account.please_enter_your_current_account_passwo'));
		
		app.confirm( _t('my_account.delete_my_account_title'), _t('my_account.are_you_sure_you_want_to_permanently_del_body'), _t('my_account.delete_btn'), function(result) {
			if (result) {
				app.showProgress( 1.0, _t('my_account.deleting_account') );
				app.api.post( 'user/delete', {
					username: app.username,
					password: $('#fe_ma_old_password').val()
				}, 
				function(resp) {
					// finished deleting, immediately log user out
					app.doUserLogout();
				} );
			}
		} );
	},
	
	onDeactivate: function() {
		// called when page is deactivated
		// this.div.html( '' );
		return true;
	}
	
} );
